from models import Attachment, EmailRecord
from pipeline import build_submission, process_inbox


SI = """SHIPPING INSTRUCTION
Shipper: Acme Ltd.
Consignee: Beta Inc.
Notify Party: Beta Inc.
Port of Loading: Shanghai (CNSHA)
Port of Discharge: Los Angeles (USLAX)
Container Count: 3
Gross Weight: 12500 KG
"""

BL = SI.replace("SHIPPING INSTRUCTION", "BILL OF LADING")


def test_pipeline_keeps_every_email_and_only_processes_comparisons() -> None:
    comparison_email = EmailRecord(
        email_id="email-2",
        subject="Please compare attached SI and BL",
        attachments=(Attachment("SI.txt", SI), Attachment("BL.txt", BL)),
    )
    general_email = EmailRecord(
        email_id="email-1",
        subject="Office holiday schedule",
        attachments=(Attachment("unreadable.txt", ""),),
    )

    output = process_inbox([comparison_email, general_email])

    assert list(output) == ["email-1", "email-2"]
    assert output["email-1"]["category"] == "general"
    assert output["email-1"]["processing_status"] == "skipped"
    assert output["email-2"]["category"] == "document_comparison"
    assert output["email-2"]["mismatch_found"] is False
    assert output["email-2"]["comparison"]["status"] == "match"
    assert set(output["email-2"]["timings_ms"]) == {
        "classification",
        "extraction",
        "comparison",
        "total",
    }
    assert all(value >= 0 for value in output["email-2"]["timings_ms"].values())


def test_submission_adapter_keeps_email_ids_and_projects_a_list_template() -> None:
    mismatching_bl = BL.replace("Container Count: 3", "Container Count: 4")
    results = process_inbox(
        [
            EmailRecord(
                email_id="email-9",
                subject="Compare SI and BL",
                attachments=(Attachment("SI.txt", SI), Attachment("BL.txt", mismatching_bl)),
            )
        ]
    )
    template = {
        "placeholder": {
            "email_type": None,
            "has_mismatch": None,
            "mismatched_fields": [{"field": None, "si_value": None, "bl_value": None}],
        }
    }

    submission = build_submission(results, template)

    assert list(submission) == ["email-9"]
    assert submission["email-9"]["email_type"] == "document_comparison"
    assert submission["email-9"]["has_mismatch"] is True
    assert submission["email-9"]["mismatched_fields"] == [
        {"field": "container_count", "si_value": "3", "bl_value": "4"}
    ]
