import json
from datetime import datetime
from unittest.mock import patch

import pytest
from dateutil import parser as dtparser  # type: ignore[import-untyped]
from kafka.consumer.fetcher import ConsumerRecord  # type: ignore[import-untyped]

from minioevents import app, from_consumer_record

_EVENT_TIME = "2023-01-15T12:34:56.000Z"
_EVENT_TIME_SERIALIZED = "2023-01-15T12:34:56Z"
_CONSUMER_RECORD = ConsumerRecord(
    topic="test",
    partition=0,
    offset=0,
    timestamp=datetime(1993, 3, 1),  # noqa: DTZ001
    timestamp_type=None,
    key="testkey",
    value="""
            {
                "Records": [
                    {
                        "responseElements": {
                            "x-amz-request-id": "x-amz-request-id",
                            "x-amz-id-2": "x-amz-id-2"
                        },
                        "eventSource": "eventsource",
                        "awsRegion": "",
                        "s3": {
                            "bucket": {
                                "name": "bucketname"
                            },
                            "object": {
                                "key": "objectkey"
                            }
                        },
                        "eventName": "eventname",
                        "eventTime": "2023-01-15T12:34:56.000Z"
                    }
                ]
            }
            """,
    headers=None,
    checksum=None,
    serialized_key_size=0,
    serialized_value_size=0,
    serialized_header_size=0,
)


@pytest.mark.parametrize(
    ("minioevent", "expected_attrs", "expected_data"),
    [
        (
            _CONSUMER_RECORD,
            {
                "id": "x-amz-request-id.x-amz-id-2",
                "source": "eventsource..bucketname",
                "specversion": "1.0",
                "type": "com.amazonaws.s3.eventname",
                "datacontenttype": "application/json",
                "subject": "objectkey",
                "time": dtparser.parse(_EVENT_TIME),
            },
            {
                "responseElements": {
                    "x-amz-request-id": "x-amz-request-id",
                    "x-amz-id-2": "x-amz-id-2",
                },
                "eventSource": "eventsource",
                "awsRegion": "",
                "s3": {
                    "bucket": {"name": "bucketname"},
                    "object": {"key": "objectkey"},
                },
                "eventName": "eventname",
                "eventTime": _EVENT_TIME,
            },
        ),
    ],
)
def test_from_consumer_record(minioevent, expected_attrs, expected_data):
    called = False
    for ce in from_consumer_record(minioevent):
        assert ce.get_attributes() == expected_attrs
        assert ce.get_data() == expected_data
        called = True
    assert called


@patch("minioevents.KafkaProducer")
@patch("minioevents.KafkaConsumer")
def test_app(mock_consumer, mock_producer):
    mock_consumer.side_effect = lambda *_, **__: [
        _CONSUMER_RECORD,
    ]
    mock_producer.return_value = mock_producer
    app(
        bootstrap_servers="server:9092",
        security_protocol="SSL",
        tls_cafile=None,
        tls_certfile=None,
        tls_keyfile=None,
        consumer_topic="ctopic",
        consumer_group="cgroup",
        consumer_auto_offset_reset="creset",
        producer_topic="ptopic",
    )
    mock_producer.send.assert_called_once_with(
        "ptopic",
        key="com.amazonaws.s3.eventname.eventsource..bucketname.objectkey",
        value=bytes(
            json.dumps(
                {
                    "id": "x-amz-request-id.x-amz-id-2",
                    "source": "eventsource..bucketname",
                    "specversion": "1.0",
                    "type": "com.amazonaws.s3.eventname",
                    "datacontenttype": "application/json",
                    "subject": "objectkey",
                    "time": _EVENT_TIME_SERIALIZED,
                    "data": {
                        "responseElements": {
                            "x-amz-request-id": "x-amz-request-id",
                            "x-amz-id-2": "x-amz-id-2",
                        },
                        "eventSource": "eventsource",
                        "awsRegion": "",
                        "s3": {
                            "bucket": {"name": "bucketname"},
                            "object": {"key": "objectkey"},
                        },
                        "eventName": "eventname",
                        "eventTime": _EVENT_TIME,
                    },
                },
            ),
            "utf-8",
        ),
        headers=[("content-type", b"application/cloudevents+json")],
    )
