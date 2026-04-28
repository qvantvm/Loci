from pathlib import Path

from loci.models.schemas import Scope, Section, new_id
from loci.services.agent_orchestrator import AgentOrchestrator
from loci.services.storage_service import StorageService


def _seed_storage(tmp_path: Path) -> tuple[StorageService, str, str]:
    storage = StorageService(data_dir=tmp_path / "data", db_path=tmp_path / "loci.sqlite")
    document = storage.create_document("Agent Source", "pasted", None, "hash")
    section = storage.create_section(
        Section(
            id=new_id("sec"),
            document_id=document.id,
            title="Grounded Agents",
            verbatim_content=(
                "Grounded agents should cite saved source sections before creating new content. "
                "The expert agent approves only content that is supported by local evidence."
            ),
            ai_summary="Grounded agents cite saved source sections.",
            metadata={"status": "draft", "provenance": "human"},
        )
    )
    return storage, document.id, section.id


def test_question_scratchpad_has_expert_final_answer_and_iteration_cap(tmp_path):
    storage, document_id, section_id = _seed_storage(tmp_path)
    orchestrator = AgentOrchestrator(storage)

    result = orchestrator.answer_user_question(
        "How should grounded agents create content?",
        Scope(document_id=document_id, section_id=section_id),
        max_iterations=99,
    )

    scratchpad = storage.get_scratchpad(result.scratchpad.id)
    assert scratchpad is not None
    assert scratchpad.kind == "question"
    assert scratchpad.status == "completed"
    assert scratchpad.max_iterations == 10
    assert scratchpad.final_answer
    entries = storage.list_scratchpad_entries(scratchpad.id)
    assert {entry.actor for entry in entries} >= {"inexpert_agent", "critique_agent", "expert_agent"}
    assert any(entry.entry_type == "decision" for entry in entries)


def test_dream_cycle_creates_generated_document_outside_sources(tmp_path):
    storage, document_id, section_id = _seed_storage(tmp_path)
    orchestrator = AgentOrchestrator(storage)

    result = orchestrator.run_dream_cycle(Scope(document_id=document_id, section_id=section_id), max_iterations=10)

    assert result.generated_document_id is not None
    generated = storage.get_document(result.generated_document_id)
    assert generated is not None
    assert generated.source_type == "ai_generated"
    assert generated.source_path is not None
    assert "/artifacts/generated_documents/" in generated.source_path
    assert "/sources/" not in generated.source_path
    assert storage.list_sections(generated.id)
