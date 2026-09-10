import csv
import io
import json
import secrets
from django.conf import settings
from django.db import connection, transaction
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.authentication import BaseAuthentication, SessionAuthentication
from rest_framework.exceptions import (
    AuthenticationFailed,
    MethodNotAllowed,
    ValidationError,
)
from rest_framework.permissions import BasePermission, SAFE_METHODS
from rest_framework.response import Response
from rest_framework.views import APIView
from .models import ExperimentRun, SensorSample, FPGAImplementation, EventMarker
from .serializers import (
    RunSerializer,
    SampleSerializer,
    ImplementationSerializer,
    EventSerializer,
)
from .services import ingest, run_summary, sensor_health, SENSORS
from .tables import paper_tables


class IngestAuthentication(BaseAuthentication):
    def authenticate(self, request):
        token = request.headers.get("Authorization", "")
        if not token.startswith("Bearer "):
            return None
        if not settings.INGEST_API_TOKEN or not secrets.compare_digest(
            token[7:].encode(), settings.INGEST_API_TOKEN.encode()
        ):
            raise AuthenticationFailed("Invalid ingestion token.")
        return (None, "ingest")

    def authenticate_header(self, request):
        return "Bearer"


class WritePermission(BasePermission):
    def has_permission(self, request, view):
        return (
            request.method in SAFE_METHODS
            or request.auth == "ingest"
            or bool(
                request.user and request.user.is_authenticated and request.user.is_staff
            )
        )


class ResearchAPI(APIView):
    authentication_classes = [IngestAuthentication, SessionAuthentication]
    permission_classes = [WritePermission]

    def handle_exception(self, exc):
        from django.core.exceptions import ValidationError as ModelValidationError

        if isinstance(exc, ModelValidationError):
            exc = ValidationError(
                exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            )
        return super().handle_exception(exc)


def integer(request, name, default, maximum):
    try:
        value = int(request.query_params.get(name, default))
    except (TypeError, ValueError):
        raise ValidationError({name: "Must be an integer."})
    if value < 1 or value > maximum:
        raise ValidationError({name: f"Must be between 1 and {maximum}."})
    return value


def filtered_samples(request, run_id=None):
    qs = SensorSample.objects.all()
    if run_id is not None:
        get_object_or_404(ExperimentRun, pk=run_id)
    elif "run_id" in request.query_params:
        run_id = integer(request, "run_id", None, 2**63 - 1)
    if run_id is not None:
        qs = qs.filter(run_id=run_id)
    bounds = {}
    for param, lookup in [("start", "timestamp__gte"), ("end", "timestamp__lte")]:
        if request.query_params.get(param):
            try:
                stamp = parse_datetime(request.query_params[param])
            except ValueError:
                stamp = None
            if stamp is None or timezone.is_naive(stamp):
                raise ValidationError(
                    {param: "Use an ISO 8601 timestamp with timezone."}
                )
            bounds[param] = stamp
            qs = qs.filter(**{lookup: stamp})
    if len(bounds) == 2 and bounds["start"] > bounds["end"]:
        raise ValidationError("start must precede end.")
    for param, field in [("quality_flag", "quality_flag"), ("state", "signal_state")]:
        value = request.query_params.get(param)
        if value:
            if value not in dict(SensorSample._meta.get_field(field).choices):
                raise ValidationError({param: "Unknown value."})
            qs = qs.filter(**{field: value})
    sensor = request.query_params.get("sensor")
    if sensor and sensor not in SENSORS:
        raise ValidationError({"sensor": "Use do, ph, tds, or temperature."})
    return qs


class SamplesAPI(ResearchAPI):
    def post(self, request, batch=False):
        payloads = request.data if batch else [request.data]
        if batch and isinstance(payloads, dict):
            if set(payloads) != {"samples"}:
                raise ValidationError(
                    "A batch object must contain only the samples array."
                )
            payloads = payloads.get("samples")
        if (
            not isinstance(payloads, list)
            or not 1 <= len(payloads) <= settings.MAX_BATCH_SIZE
        ):
            raise ValidationError(f"Expected 1–{settings.MAX_BATCH_SIZE} samples.")
        samples = ingest(payloads)
        return Response(
            {"created": len(samples), "ids": [s.pk for s in samples]}, status=201
        )


class HistoryAPI(ResearchAPI):
    def get(self, request, run_id=None):
        qs = filtered_samples(request, run_id)
        limit = integer(request, "limit", 500, 5000)
        page = integer(request, "page", 1, 1000000)
        count = qs.count()
        target = (
            integer(request, "downsample", limit, 5000)
            if "downsample" in request.query_params
            else None
        )
        if target:
            if page != 1:
                raise ValidationError(
                    {"page": "Downsampled history covers the interval; use page 1."}
                )
            # Keep both interval endpoints. A single point means the latest point.
            # Only the requested rows are transferred from the database.
            from django.db.models import Window, F
            from django.db.models.functions import RowNumber

            size = min(target, count)
            positions = (
                [count]
                if size == 1
                else [1 + i * (count - 1) // (size - 1) for i in range(size)]
            )
            selected = (
                qs.annotate(
                    row_number=Window(
                        expression=RowNumber(),
                        order_by=[F("timestamp").asc(), F("id").asc()],
                    )
                )
                .filter(row_number__in=positions)
                .order_by("timestamp", "id")
            )
            rows = list(selected)
        else:
            rows = list(
                qs.order_by("-timestamp", "-id")[(page - 1) * limit : page * limit]
            )
            rows.reverse()
        data = SampleSerializer(rows, many=True).data
        sensor = request.query_params.get("sensor")
        if sensor:
            data = [
                {
                    k: v
                    for k, v in row.items()
                    if k.startswith(sensor + "_")
                    or k
                    in (
                        "id",
                        "timestamp",
                        "run_id",
                        "source",
                        "quality_flag",
                        "signal_state",
                        "packet_valid",
                        "packet_crc_ok",
                    )
                }
                for row in data
            ]
        return Response(
            dict(
                count=count,
                page=page,
                results=data,
                downsampled=bool(target),
                next_page=page + 1 if not target and page * limit < count else None,
            )
        )


class LatestAPI(ResearchAPI):
    def get(self, request):
        # Gateway receipt order remains reliable when device clocks drift.
        sample = (
            filtered_samples(request)
            .select_related("run")
            .order_by("-received_at", "-id")
            .first()
        )
        return Response(
            {
                "sample": SampleSerializer(sample).data if sample else None,
                "sensor_health": sensor_health(sample, sample.run if sample else None),
            }
        )


class RunsAPI(ResearchAPI):
    def get(self, request, run_id=None):
        if run_id:
            return Response(
                RunSerializer(get_object_or_404(ExperimentRun, pk=run_id)).data
            )
        page, limit = integer(request, "page", 1, 1000000), integer(
            request, "limit", 100, 500
        )
        qs = ExperimentRun.objects.order_by("-created_at", "-pk")
        count = qs.count()
        return Response(
            dict(
                count=count,
                page=page,
                next_page=page + 1 if page * limit < count else None,
                results=RunSerializer(
                    qs[(page - 1) * limit : page * limit], many=True
                ).data,
            )
        )

    def post(self, request, run_id=None):
        if run_id is not None:
            raise MethodNotAllowed("POST")
        serializer = RunSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)

    @transaction.atomic
    def patch(self, request, run_id=None):
        if run_id is None:
            raise MethodNotAllowed("PATCH")
        serializer = RunSerializer(
            get_object_or_404(ExperimentRun, pk=run_id), data=request.data, partial=True
        )
        serializer.is_valid(raise_exception=True)
        if (
            "source" in serializer.validated_data
            and serializer.instance.samples.exists()
            and serializer.validated_data["source"] != serializer.instance.source
        ):
            raise ValidationError(
                "Cannot change source after samples have been logged."
            )
        serializer.save()
        return Response(serializer.data)


class SummaryAPI(ResearchAPI):
    def get(self, request, run_id):
        run = get_object_or_404(
            ExperimentRun.objects.select_related("implementation"), pk=run_id
        )
        return Response(
            run_summary(
                run, filtered_samples(request, run_id) if request.query_params else None
            )
        )


class StatusAPI(ResearchAPI):
    def get(self, request):
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        latest = SensorSample.objects.order_by("-received_at").first()
        fpga = (
            SensorSample.objects.filter(fpga_latency_us__isnull=False)
            .order_by("-received_at")
            .first()
        )
        active = (
            ExperimentRun.objects.filter(status="RUNNING")
            .order_by("-started_at")
            .first()
        )
        return Response(
            dict(
                webserver="ok",
                database="ok",
                database_vendor=connection.vendor,
                sample_count=SensorSample.objects.count(),
                latest_sensor_packet=latest.timestamp if latest else None,
                latest_fpga_packet=fpga.timestamp if fpga else None,
                latest_api_ingest_time=latest.received_at if latest else None,
                online=bool(
                    latest
                    and (timezone.now() - latest.received_at).total_seconds()
                    < settings.SENSOR_OFFLINE_SECONDS
                ),
                source=latest.source if latest else None,
                active_run=active.pk if active else None,
                software_version=settings.SOFTWARE_VERSION,
            )
        )


class CatalogAPI(ResearchAPI):
    def get(self, request, kind):
        model, serializer = (
            (FPGAImplementation, ImplementationSerializer)
            if kind == "implementations"
            else (EventMarker, EventSerializer)
        )
        qs = model.objects.order_by("-pk")
        if kind == "events":
            if "run_id" in request.query_params:
                qs = qs.filter(run_id=integer(request, "run_id", None, 2**63 - 1))
            if request.query_params.get("event_type"):
                qs = qs.filter(event_type=request.query_params["event_type"])
        page, limit = integer(request, "page", 1, 1000000), integer(
            request, "limit", 100, 1000
        )
        count = qs.count()
        return Response(
            dict(
                count=count,
                page=page,
                next_page=page + 1 if page * limit < count else None,
                results=serializer(
                    qs[(page - 1) * limit : page * limit], many=True
                ).data,
            )
        )

    def post(self, request, kind):
        cls = ImplementationSerializer if kind == "implementations" else EventSerializer
        serializer = cls(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=201)


class Echo:
    def write(self, value):
        return value


class TablesAPI(ResearchAPI):
    def get(self, request, run_id):
        run = get_object_or_404(ExperimentRun, pk=run_id)
        filters = {"start", "end", "quality_flag", "state", "sensor"} & set(
            request.query_params
        )
        tables = paper_tables(
            run_summary(run, filtered_samples(request, run_id) if filters else None)
        )
        if request.query_params.get("download") == "csv":
            writer = csv.writer(Echo())

            def stream():
                for key, table in tables.items():
                    yield writer.writerow(
                        [key, table["title"], "Source: " + run.source]
                    )
                    yield writer.writerow(table["headers"])
                    for row in table["rows"]:
                        yield writer.writerow(
                            ["N/A" if v is None else safe_cell(v) for v in row]
                        )
                    yield writer.writerow([])

            response = StreamingHttpResponse(
                stream(), content_type="text/csv; charset=utf-8"
            )
            response["Content-Disposition"] = (
                f'attachment; filename="run-{run_id}-tables.csv"'
            )
            return response
        return Response(tables)


def safe_cell(value):
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str) and value.startswith(
        ("=", "+", "-", "@", "\t", "\r", "\n")
    ):
        return "'" + value
    return value


class ExportAPI(ResearchAPI):
    def get(self, request, run_id):
        get_object_or_404(ExperimentRun, pk=run_id)
        # Validate before returning the streaming response so malformed filters
        # produce a normal HTTP 400 rather than failing after headers are sent.
        samples = filtered_samples(request, run_id).order_by("timestamp", "id")
        fields = [f.attname for f in SensorSample._meta.fields]
        writer = csv.writer(Echo())

        def stream():
            yield "\ufeff" + writer.writerow(fields)
            for row in samples.values_list(*fields).iterator(chunk_size=2000):
                yield writer.writerow([safe_cell(v) for v in row])

        response = StreamingHttpResponse(
            stream(), content_type="text/csv; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="run-{run_id}.csv"'
        return response


class ImportAPI(ResearchAPI):
    def post(self, request, run_id):
        run = get_object_or_404(ExperimentRun, pk=run_id)
        upload = request.FILES.get("file")
        if not upload or upload.size > 10 * 1024 * 1024:
            raise ValidationError("Provide a UTF-8 CSV file of at most 10 MB.")
        try:
            mapping = json.loads(request.data.get("mapping", "{}"))
            if not isinstance(mapping, dict) or any(
                not isinstance(k, str)
                or not isinstance(v, str)
                or not k.strip()
                or not v.strip()
                for k, v in mapping.items()
            ):
                raise ValidationError(
                    "mapping must be an object of nonempty CSV column names to field names."
                )
            reader = csv.DictReader(
                io.StringIO(upload.read().decode("utf-8-sig")), strict=True
            )
            headers = reader.fieldnames or []
            if not headers or any(not h.strip() for h in headers):
                raise ValidationError("CSV must contain nonempty column names.")
            if len(set(headers)) != len(headers):
                raise ValidationError("Duplicate column names.")
            if set(mapping) - set(headers):
                raise ValidationError(
                    {"mapping": "Mapping contains column names not present in the CSV."}
                )
            targets = [mapping.get(h, h) for h in headers]
            if len(set(targets)) != len(targets):
                raise ValidationError(
                    {"mapping": "Multiple CSV columns map to the same field."}
                )
            required = {"do_raw", "ph_raw", "tds_raw", "temperature_raw"}
            missing = sorted(required - set(mapping.get(h, h) for h in headers))
            report = dict(
                total_rows=0,
                successful_rows=0,
                failed_rows=0,
                missing_columns=missing,
                conversion_errors=[],
            )
            payloads = []
            for number, row in enumerate(reader, 2):
                if number > settings.MAX_IMPORT_ROWS + 1:
                    raise ValidationError(
                        "CSV exceeds configured row limit; split the file. No rows imported."
                    )
                report["total_rows"] += 1
                try:
                    if None in row or any(v is None for v in row.values()):
                        raise ValueError("Row has wrong number of columns.")
                    data = {
                        mapping.get(k, k): v
                        for k, v in row.items()
                        if v != ""
                        and mapping.get(k, k) not in ("id", "received_at", "run_id")
                    }
                    data["run_id"] = run.pk
                    for name in ("sensor_status", "extra_sensors"):
                        if name in data:
                            data[name] = json.loads(data[name])
                    serializer = SampleSerializer(
                        data=data, context={"runs": {run.pk: run}}
                    )
                    serializer.is_valid(raise_exception=True)
                    payloads.append(data)
                except (ValueError, ValidationError) as exc:
                    report["failed_rows"] += 1
                    report["conversion_errors"].append(
                        {"row": number, "errors": str(exc)}
                    )
            # Explicit partial import: valid rows committed together; every failed row reported.
            if payloads:
                report["successful_rows"] = len(ingest(payloads))
            return Response(report, status=201 if payloads else 400)
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            csv.Error,
            ValueError,
            TypeError,
        ) as exc:
            raise ValidationError(f"Malformed CSV/mapping: {exc}")
