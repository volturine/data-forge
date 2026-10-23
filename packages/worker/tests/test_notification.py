import json
from dataclasses import dataclass
from unittest.mock import patch

import polars as pl
import pyarrow as pa  # type: ignore[import-untyped]
import pytest
from pydantic import ValidationError

from dataforge_protocol import analysis_pb2, enums_pb2
from operations.notification import NotificationHandler, NotificationParams
from operations.step_converter import analysis_pipeline_to_execution_payload, convert_step_format
from operations.template_placeholders import render_template_placeholders
from runtime.compute_service import _prepare_pipeline_notifications
from runtime.notification_delivery import (
    extract_staged_deliveries,
    render_template,
    staged_column_name,
    strip_staged_preview,
)


@dataclass(frozen=True)
class MockSubscriber:
    chat_id: str
    bot_token: str


def _pipeline_with(step: analysis_pb2.AnalysisPipelineStep) -> analysis_pb2.AnalysisPipelinePayload:
    return analysis_pb2.AnalysisPipelinePayload(
        analysis_id="analysis-1",
        tabs=[
            analysis_pb2.AnalysisPipelineTab(
                id="tab-1",
                datasource=analysis_pb2.AnalysisPipelineDatasource(id="datasource-1", source_type=enums_pb2.DATA_SOURCE_TYPE_FILE),
                output=analysis_pb2.AnalysisPipelineOutput(result_id="result-1", filename="result.csv", format=enums_pb2.EXPORT_FORMAT_CSV),
                steps=[step],
            )
        ],
    )


def _collect(params: dict[str, object], frame: pl.DataFrame | None = None) -> pl.DataFrame:
    source = frame if frame is not None else pl.DataFrame({"body": ["hello"]})
    return NotificationHandler()(source.lazy(), params, step_id="step-1").collect()


class TestNotificationParams:
    def test_requires_recipient_and_input_columns(self) -> None:
        with pytest.raises(ValidationError, match="recipient"):
            NotificationParams.model_validate({"method": "email", "input_columns": ["body"]})
        with pytest.raises(ValidationError, match="input_columns"):
            NotificationParams.model_validate({"method": "email", "recipient": "a@example.com"})

    def test_accepts_protocol_step_config_with_recipient_source(self) -> None:
        # Every stored notification config carries recipient_source (backend default).
        step = analysis_pb2.AnalysisPipelineStep(
            id="notify",
            step_type=enums_pb2.STEP_TYPE_NOTIFICATION,
            config=analysis_pb2.StepConfig(
                notification=analysis_pb2.NotificationConfig(
                    method=enums_pb2.NOTIFICATION_METHOD_EMAIL,
                    recipient="a@example.com",
                    recipient_source=enums_pb2.RECIPIENT_SOURCE_MANUAL,
                    input_columns=["body"],
                    batch_size=10,
                )
            ),
        )
        converted = convert_step_format(analysis_pipeline_to_execution_payload(_pipeline_with(step))["tabs"][0]["steps"][0])

        assert converted.params["recipient_source"] == enums_pb2.RECIPIENT_SOURCE_MANUAL

    def test_recipient_column_is_an_explicit_recipient_source(self) -> None:
        params = NotificationParams.model_validate({"method": "telegram", "recipient_column": "chat_id", "input_columns": ["body"]})
        assert params.recipient_column == "chat_id"

    def test_rejects_unknown_configuration(self) -> None:
        with pytest.raises(ValidationError):
            NotificationParams.model_validate(
                {
                    "method": "email",
                    "recipient": "a@example.com",
                    "input_columns": ["body"],
                    "unknown": True,
                }
            )


class TestRenderTemplatePlaceholders:
    def test_renders_known_values_and_keeps_unknown_placeholders(self) -> None:
        assert render_template_placeholders("{{title}}: {{body}} {{missing}}", {"title": "A", "body": 2}) == "A: 2 {{missing}}"


class TestNotificationHandler:
    def test_stages_email_commands_without_network_side_effects(self) -> None:
        result = _collect(
            {
                "method": "email",
                "recipient": "dest@test.com",
                "input_columns": ["body"],
                "output_column": "send_status",
                "message_template": "Msg: {{body}}",
                "subject_template": "Subj: {{body}}",
            },
            pl.DataFrame({"body": ["hello", "world"]}),
        )

        command_column = staged_column_name("step-1")
        assert result["send_status"].to_list() == ["staged", "staged"]
        assert json.loads(result[command_column][0]) == [
            {
                "body": "Msg: hello",
                "method": "email",
                "recipient": "dest@test.com",
                "subject": "Subj: hello",
            }
        ]

    def test_stages_one_telegram_command_per_recipient(self) -> None:
        result = _collect(
            {
                "method": "telegram",
                "recipient": "111, 222",
                "input_columns": ["body"],
                "message_template": "{{body}}",
                "bot_token": "token",
            }
        )
        commands = json.loads(result[staged_column_name("step-1")][0])
        assert [command["recipient"] for command in commands] == ["111", "222"]
        assert all(command["bot_token"] == "token" for command in commands)

    def test_recipient_column_overrides_static_recipient(self) -> None:
        result = _collect(
            {
                "method": "telegram",
                "recipient": "static",
                "recipient_column": "chat_ids",
                "input_columns": ["body"],
            },
            pl.DataFrame({"body": ["hello"], "chat_ids": [["one", "two"]]}),
        )
        commands = json.loads(result[staged_column_name("step-1")][0])
        assert [command["recipient"] for command in commands] == ["one", "two"]

    def test_preserves_rows_and_handles_empty_input(self) -> None:
        result = _collect(
            {"method": "email", "recipient": "a@example.com", "input_columns": ["body"]},
            pl.DataFrame({"body": []}, schema={"body": pl.String}),
        )
        assert result.height == 0
        assert result.columns == ["body", "notification_status", staged_column_name("step-1")]

    def test_missing_input_column_fails_before_execution(self) -> None:
        with pytest.raises(ValueError, match="not found"):
            NotificationHandler()(
                pl.DataFrame({"body": ["hello"]}).lazy(),
                {"method": "email", "recipient": "a@example.com", "input_columns": ["missing"]},
                step_id="step-1",
            )


class TestStagedDeliveryExtraction:
    def test_removes_internal_columns_and_returns_commands(self) -> None:
        command_column = staged_column_name("step-1")
        table = pa.table(
            {
                "value": [1],
                command_column: [
                    json.dumps(
                        [
                            {
                                "method": "email",
                                "recipient": "a@example.com",
                                "subject": "Ready",
                                "body": "Done",
                            }
                        ]
                    )
                ],
            }
        )

        sanitized, deliveries = extract_staged_deliveries(table)

        assert sanitized.column_names == ["value"]
        assert deliveries[0]["recipient"] == "a@example.com"

    def test_preview_never_exposes_internal_command_columns(self) -> None:
        command_column = staged_column_name("step-1")
        result = strip_staged_preview({"schema": {"value": "Int64", command_column: "String"}, "data": [{"value": 1, command_column: "[]"}]})
        assert result == {"schema": {"value": "Int64"}, "data": [{"value": 1}]}


class TestPreparePipelineNotifications:
    def test_output_email_is_rendered(self) -> None:
        with patch("runtime.compute_service.client_from_env") as client:
            client.return_value.telegram_targets.return_value = []
            deliveries = _prepare_pipeline_notifications(
                context={"analysis_name": "Test", "status": "success", "datasource_id": "ds-1"},
                output_notification={
                    "method": "email",
                    "recipient": "admin@test.com",
                    "subject_template": "Build: {{analysis_name}}",
                    "body_template": "Status: {{status}}",
                },
            )
        assert deliveries == [
            {
                "method": "email",
                "recipient": "admin@test.com",
                "subject": "Build: Test",
                "body": "Status: success",
            }
        ]

    def test_subscriber_targets_are_resolved_before_publication(self) -> None:
        with patch("runtime.compute_service.client_from_env") as client:
            client.return_value.telegram_targets.return_value = [MockSubscriber("999", "token")]
            deliveries = _prepare_pipeline_notifications(context={"analysis_name": "Test", "status": "success", "datasource_id": "ds-1"})
        assert deliveries[0]["recipient"] == "999"


class TestRenderTemplate:
    def test_replaces_context_values(self) -> None:
        assert render_template("{{name}} is {{status}}", {"name": "Build", "status": "ready"}) == "Build is ready"
