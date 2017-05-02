from django.test import override_settings
from unittest.mock import MagicMock, patch
from kafka.consumer.fetcher import ConsumerRecord
from kafka.structs import TopicPartition
from rest_framework.exceptions import ValidationError
from logpipe import Consumer
from logpipe.exceptions import InvalidMessageError, UnknownMessageVersionError
from logpipe.tests.common import BaseTest, TOPIC_STATES
import binascii


LOGPIPE = {
    'KAFKA_BOOTSTRAP_SERVERS': ['kafka:9092'],
}


class ConsumerTest(BaseTest):
    @override_settings(LOGPIPE=LOGPIPE)
    @patch('kafka.KafkaConsumer')
    def test_normal_consume(self, KafkaConsumer):
        # Make a fake consumer to generate a message
        fake_kafka_consumer = self.mock_consumer(KafkaConsumer,
            value=b'json:{"message":{"code":"NY","name":"New York"},"version":1,"type":"us-state"}')

        # Test the values sent to our serializer match the message
        def save(ser):
            self.assertEqual(ser.validated_data['code'], 'NY')
            self.assertEqual(ser.validated_data['name'], 'New York')
        FakeStateSerializer = self.mock_state_serializer(save)

        # Consume a message
        consumer = Consumer(TOPIC_STATES, consumer_timeout_ms=500)
        consumer.register(FakeStateSerializer)
        consumer.run(iter_limit=1)

        # Test the expected mocks where called
        KafkaConsumer.assert_called_once_with(
            auto_offset_reset='earliest',
            bootstrap_servers=['kafka:9092'],
            consumer_timeout_ms=500,
            enable_auto_commit=False)
        fake_kafka_consumer.partitions_for_topic.assert_called_once_with(TOPIC_STATES)
        fake_kafka_consumer.assign.assert_called_once_with([
            TopicPartition(partition=0, topic=TOPIC_STATES),
            TopicPartition(partition=1, topic=TOPIC_STATES),
        ])

        self.assertEqual(KafkaConsumer.call_count, 1)
        self.assertEqual(FakeStateSerializer.call_count, 1)
        self.assertEqual(fake_kafka_consumer.__next__.call_count, 1)
        self.assertEqual(self.serializers['state'].save.call_count, 1)

        consumer.run(iter_limit=1)

        self.assertEqual(KafkaConsumer.call_count, 1)
        self.assertEqual(FakeStateSerializer.call_count, 2)
        self.assertEqual(fake_kafka_consumer.__next__.call_count, 2)
        self.assertEqual(self.serializers['state'].save.call_count, 1)


    @patch('kafka.KafkaConsumer')
    def test_missing_version(self, KafkaConsumer):
        self.mock_consumer(KafkaConsumer,
            value=b'json:{"message":{"code":"NY","name":"New York"}}')

        consumer = Consumer(TOPIC_STATES, consumer_timeout_ms=500)
        with self.assertRaises(InvalidMessageError):
            consumer.run(iter_limit=1)


    @patch('kafka.KafkaConsumer')
    def test_missing_message(self, KafkaConsumer):
        self.mock_consumer(KafkaConsumer,
            value=b'json:{"version":1}')

        consumer = Consumer(TOPIC_STATES, consumer_timeout_ms=500)
        with self.assertRaises(InvalidMessageError):
            consumer.run(iter_limit=1)


    @patch('kafka.KafkaConsumer')
    def test_unknown_version(self, KafkaConsumer):
        self.mock_consumer(KafkaConsumer,
            value=b'json:{"message":{"code":"NY","name":"New York"},"version":2,"type":"us-state"}')
        FakeStateSerializer = self.mock_state_serializer()

        consumer = Consumer(TOPIC_STATES, consumer_timeout_ms=500)
        consumer.register(FakeStateSerializer)
        with self.assertRaises(UnknownMessageVersionError):
            consumer.run(iter_limit=1)
        self.assertEqual(FakeStateSerializer.call_count, 0)


    @patch('kafka.KafkaConsumer')
    def test_invalid_message(self, KafkaConsumer):
        self.mock_consumer(KafkaConsumer,
            value=b'json:{"message":{"code":"NYC","name":"New York"},"version":1,"type":"us-state"}')
        FakeStateSerializer = self.mock_state_serializer()

        consumer = Consumer(TOPIC_STATES, consumer_timeout_ms=500)
        consumer.register(FakeStateSerializer)
        with self.assertRaises(ValidationError):
            consumer.run(iter_limit=1)
        self.assertEqual(FakeStateSerializer.call_count, 1)
        self.assertEqual(self.serializers['state'].save.call_count, 0)


    def mock_consumer(self, KafkaConsumer, value):
        # Mock a consumer object
        fake_kafka_consumer = MagicMock()

        # Should return a record when used as an iterator
        record = ConsumerRecord(
            topic=TOPIC_STATES,
            partition=0,
            offset=42,
            timestamp=1467649216540,
            timestamp_type=0,
            key=b'NY',
            value=value,
            checksum=binascii.crc32(value),
            serialized_key_size=b'NY',
            serialized_value_size=value)
        fake_kafka_consumer.__next__.return_value = record

        # Return some partitions
        fake_kafka_consumer.partitions_for_topic.return_value = set([0, 1])

        # Make class instantiation return our mock
        KafkaConsumer.return_value = fake_kafka_consumer

        return fake_kafka_consumer