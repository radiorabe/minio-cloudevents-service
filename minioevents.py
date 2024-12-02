"""MinIO Events to CloudEvents Bridge."""

from __future__ import annotations

import json
import logging
import signal
import sys
from typing import TYPE_CHECKING, Any, NoReturn

from cloudevents.http import CloudEvent
from cloudevents.kafka import KafkaMessage, to_structured
from configargparse import ArgumentParser  # type: ignore[import-untyped]
from kafka import KafkaConsumer, KafkaProducer  # type: ignore[import-untyped]

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Generator

    from kafka.consumer.fetcher import ConsumerRecord  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


def from_consumer_record(msg: ConsumerRecord) -> Generator[CloudEvent, None, None]:
    """Convert msg to an array of CloudEvents using a naive implementation of https://github.com/cloudevents/spec/blob/main/cloudevents/adapters/aws-s3.md."""
    for rec in json.loads(msg.value).get("Records", []):
        yield CloudEvent(
            {
                "id": ".".join(
                    [
                        rec.get("responseElements", {}).get("x-amz-request-id"),
                        rec.get("responseElements", {}).get("x-amz-id-2"),
                    ],
                ),
                "source": ".".join(
                    [
                        rec.get("eventSource"),
                        rec.get("awsRegion"),
                        rec.get("s3", {}).get("bucket", {}).get("name"),
                    ],
                ),
                "specversion": "1.0",
                "type": ".".join(
                    [
                        "com.amazonaws.s3",
                        rec.get("eventName"),
                    ],
                ),
                "datacontenttype": "application/json",
                "subject": rec.get("s3", {}).get("object", {}).get("key"),
                "time": rec.get("eventTime"),
            },
            rec,
        )


def app(  # noqa: PLR0913
    bootstrap_servers: list[str],
    security_protocol: str,
    tls_cafile: str,
    tls_certfile: str,
    tls_keyfile: str,
    consumer_topic: str,
    consumer_group: str,
    consumer_auto_offset_reset: str,
    producer_topic: str,
) -> None:
    """Set up kafka consumer and producer, block until SIGINT while reading messages."""
    consumer = KafkaConsumer(
        consumer_topic,
        bootstrap_servers=bootstrap_servers,
        security_protocol=security_protocol,
        group_id=consumer_group,
        auto_offset_reset=consumer_auto_offset_reset,
        ssl_cafile=tls_cafile,
        ssl_certfile=tls_certfile,
        ssl_keyfile=tls_keyfile,
    )
    producer = KafkaProducer(
        bootstrap_servers=bootstrap_servers,
        security_protocol=security_protocol,
        retries=5,
        max_in_flight_requests_per_connection=1,
        key_serializer=lambda k: bytes(k, "utf-8"),
        ssl_cafile=tls_cafile,
        ssl_certfile=tls_certfile,
        ssl_keyfile=tls_keyfile,
    )

    def on_sigint(*_: Any) -> NoReturn:  # noqa: ANN401 # pragma: no cover
        consumer.close()
        producer.flush()
        producer.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, on_sigint)

    def on_send_error(ex: Exception) -> None:  # pragma: no cover
        logger.error("Failed to send CloudEvent", exc_info=ex)

    def _key_mapper(ce: CloudEvent) -> str:
        return ".".join(
            [
                ce.get("type"),  # type: ignore[list-item]
                ce.get("source"),  # type: ignore[list-item]
                ce.get("subject"),  # type: ignore[list-item]
            ],
        )

    for msg in consumer:
        for ce in from_consumer_record(msg):
            km: KafkaMessage = to_structured(ce, key_mapper=_key_mapper)
            headers: list[tuple[str, bytes]] | None
            if km.headers:
                headers = list(km.headers.items())
            producer.send(
                producer_topic,
                key=km.key,
                value=km.value,
                headers=headers,
            ).add_errback(on_send_error)
        producer.flush()


def main() -> None:  # pragma: no cover
    """CLI entrypoint parses args, sets up logging, and calls `app()`."""
    parser = ArgumentParser(__name__)
    parser.add(
        "--kafka-bootstrap-servers",
        required=True,
        env_var="KAFKA_BOOTSTRAP_SERVERS",
    )
    parser.add(
        "--kafka-security-protocol",
        default="PLAINTEXT",
        env_var="KAFKA_SECURITY_PROTOCOL",
    )
    parser.add(
        "--kafka-tls-cafile",
        default=None,
        env_var="KAFKA_TLS_CAFILE",
    )
    parser.add(
        "--kafka-tls-certfile",
        default=None,
        env_var="KAFKA_TLS_CERTFILE",
    )
    parser.add(
        "--kafka-tls-keyfile",
        default=None,
        env_var="KAFKA_TLS_KEYFILE",
    )
    parser.add(
        "--kafka-consumer-topic",
        default="minioevents",
        env_var="KAFKA_CONSUMER_TOPIC",
    )
    parser.add(
        "--kafka-consumer-group",
        default=__name__,
        env_var="KAFKA_CONSUMER_GROUP",
    )
    parser.add(
        "--kafka-consumer-auto-offset-reset",
        default="latest",
        env_var="KAFKA_CONSUMER_AUTO_OFFSET_RESET",
    )
    parser.add(
        "--kafka-producer-topic",
        default="cloudevents",
        env_var="KAFKA_PRODUCER_TOPIC",
    )
    parser.add(
        "--quiet",
        "-q",
        default=False,
        action="store_true",
        env_var="MINIOEVENTS_QUIET",
    )

    options = parser.parse_args()

    if not options.quiet:
        logging.basicConfig(level=logging.INFO)
    logger.info("Starting %s", __name__)

    app(
        bootstrap_servers=options.kafka_bootstrap_servers,
        security_protocol=options.kafka_security_protocol,
        tls_cafile=options.kafka_tls_cafile,
        tls_certfile=options.kafka_tls_certfile,
        tls_keyfile=options.kafka_tls_keyfile,
        consumer_topic=options.kafka_consumer_topic,
        consumer_group=options.kafka_consumer_group,
        consumer_auto_offset_reset=options.kafka_consumer_auto_offset_reset,
        producer_topic=options.kafka_producer_topic,
    )


if __name__ == "__main__":  # pragma: no cover
    main()
