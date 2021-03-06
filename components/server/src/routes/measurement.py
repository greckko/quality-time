"""Measurement routes."""

import logging
import time
from datetime import date
from typing import Dict, Iterator, cast

import bottle
from pymongo.database import Database

from database import sessions
from database.datamodels import latest_datamodel
from database.measurements import (
    all_measurements, count_measurements, insert_new_measurement, latest_measurement, latest_successful_measurement,
    update_measurement_end)
from database.reports import latest_metric, latest_reports
from model.data import SourceData
from server_utilities.functions import report_date_time
from server_utilities.type import MetricId, SourceId


@bottle.post("/internal-api/v3/measurements")
def post_measurement(database: Database) -> Dict:
    """Put the measurement in the database."""
    measurement = dict(bottle.request.json)
    metric_uuid = measurement["metric_uuid"]
    if not (metric := latest_metric(database, metric_uuid)):  # pylint: disable=superfluous-parens
        return dict(ok=False)  # Metric does not exist, must've been deleted while being measured
    data_model = latest_datamodel(database)
    if latest := latest_measurement(database, metric_uuid):
        latest_successful = latest_successful_measurement(database, metric_uuid)
        latest_sources = latest_successful["sources"] if latest_successful else latest["sources"]
        copy_entity_user_data(latest_sources, measurement["sources"])
        if not debt_target_expired(data_model, metric, latest) and latest["sources"] == measurement["sources"]:
            # If the new measurement is equal to the previous one, merge them together
            update_measurement_end(database, latest["_id"])
            return dict(ok=True)
    return insert_new_measurement(database, data_model, metric, measurement)


def copy_entity_user_data(old_sources, new_sources) -> None:
    """Copy the entity user data from the old sources to the new sources."""
    for old_source, new_source in zip(old_sources, new_sources):
        new_entity_keys = {entity["key"] for entity in new_source.get("entities", [])}
        # Sometimes the key Quality-time generates for entities needs to change, e.g. when it turns out not to be
        # unique. Create a mapping of old keys to new keys so we can move the entity user data to the new keys
        changed_entity_keys = {
            entity["old_key"]: entity["key"] for entity in new_source.get("entities", []) if "old_key" in entity}
        # Copy the user data of entities that still exist in the new measurement:
        for entity_key, attributes in old_source.get("entity_user_data", {}).items():
            if entity_key in changed_entity_keys:
                new_entity_key = changed_entity_keys[entity_key]
                new_source.setdefault("entity_user_data", {})[new_entity_key] = attributes
            elif entity_key in new_entity_keys:
                new_source.setdefault("entity_user_data", {})[entity_key] = attributes


def debt_target_expired(data_model, metric, measurement) -> bool:
    """Return whether the technical debt target is expired.

    Technical debt can expire because it was turned off or because the end date passed.
    """
    metric_scales = data_model["metrics"][metric["type"]]["scales"]
    any_debt_target = any(measurement.get(scale, {}).get("debt_target") is not None for scale in metric_scales)
    if not any_debt_target:
        return False
    return metric.get("accept_debt") is False or \
           (metric.get("debt_end_date") or date.max.isoformat()) < date.today().isoformat()  # pragma: no cover-behave


@bottle.post("/api/v3/measurement/<metric_uuid>/source/<source_uuid>/entity/<entity_key>/<attribute>")
def set_entity_attribute(metric_uuid: MetricId, source_uuid: SourceId, entity_key: str, attribute: str,
                         database: Database) -> Dict:
    """Set an entity attribute."""
    data_model = latest_datamodel(database)
    reports = latest_reports(database)
    data = SourceData(data_model, reports, source_uuid)
    measurement = latest_measurement(database, metric_uuid)
    source = [s for s in measurement["sources"] if s["source_uuid"] == source_uuid][0]
    entity = [e for e in source["entities"] if e["key"] == entity_key][0]
    entity_description = "/".join([entity[key] for key in entity.keys() if key not in ("key", "url")])
    old_value = source.get("entity_user_data", {}).get(entity_key, {}).get(attribute) or ""
    value = dict(bottle.request.json)[attribute]
    source.setdefault("entity_user_data", {}).setdefault(entity_key, {})[attribute] = value
    user = sessions.user(database)
    measurement["delta"] = dict(
        uuids=[data.report_uuid, data.subject_uuid, metric_uuid, source_uuid],
        description=f"{user['user']} changed the {attribute} of '{entity_description}' from '{old_value}' to "
                    f"'{value}'.",
        email=user["email"])
    return insert_new_measurement(database, data.datamodel, data.metric, measurement)


def sse_pack(event_id: int, event: str, data: int, retry: str = "2000") -> str:
    """Pack data in Server-Sent Events (SSE) format."""
    return f"retry: {retry}\nid: {event_id}\nevent: {event}\ndata: {data}\n\n"


@bottle.get("/api/v3/nr_measurements")
def stream_nr_measurements(database: Database) -> Iterator[str]:
    """Return the number of measurements as server sent events."""
    # Keep event IDs consistent
    event_id = int(bottle.request.get_header("Last-Event-Id", -1)) + 1

    # Set the response headers
    bottle.response.set_header("Connection", "keep-alive")
    bottle.response.set_header("Content-Type", "text/event-stream")
    bottle.response.set_header("Cache-Control", "no-cache")

    # Provide an initial data dump to each new client and set up our message payload with a retry value in case of
    # connection failure
    nr_measurements = count_measurements(database)
    logging.info("Initializing nr_measurements stream with %s measurements", nr_measurements)
    yield sse_pack(event_id, "init", nr_measurements)
    skipped = 0
    # Now give the client updates as they arrive
    while True:
        time.sleep(10)
        if (new_nr_measurements := count_measurements(database)) > nr_measurements or skipped > 5:
            skipped = 0
            nr_measurements = new_nr_measurements
            event_id += 1
            logging.info(
                "Updating nr_measurements stream with %s measurements", nr_measurements)
            yield sse_pack(event_id, "delta", nr_measurements)
        else:
            skipped += 1


@bottle.get("/api/v3/measurements/<metric_uuid>")
def get_measurements(metric_uuid: MetricId, database: Database) -> Dict:
    """Return the measurements for the metric."""
    metric_uuid = cast(MetricId, metric_uuid.split("&")[0])
    return dict(measurements=list(all_measurements(database, metric_uuid, report_date_time())))
