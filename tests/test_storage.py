from pathlib import Path

from loci.models.schemas import AIArtifact, AgentScratchpad, DiscussionMessage, ResearchFragment, Section, new_id
from loci.services.storage_service import StorageService


def test_storage_crud_round_trips_json_and_threads(tmp_path):
    storage = StorageService(data_dir=tmp_path / "data")
    source_path, digest = storage.save_pasted_source("Original text", ".txt")
    document = storage.create_document("Doc", "pasted", source_path, digest, {"kind": "test"})
    section = storage.create_section(
        Section(
            id=new_id("sec"),
            document_id=document.id,
            title="Intro",
            level=1,
            order_index=0,
            verbatim_content="Original text",
            ai_summary="AI summary",
            source_char_start=0,
            source_char_end=13,
            metadata={"warning": False},
        )
    )
    artifact = storage.create_artifact(
        AIArtifact(
            id=new_id("art"),
            document_id=document.id,
            section_id=section.id,
            artifact_type="summary",
            content="AI summary",
            grounding=[{"section_id": section.id, "quote": "Original text"}],
            model="fallback-local",
            prompt_version="test",
        )
    )
    thread = storage.get_or_create_root_thread(document.id, section.id)
    message = storage.create_message(
        DiscussionMessage(
            id=new_id("msg"),
            thread_id=thread.id,
            actor="user",
            content="Question?",
            grounding=[],
        )
    )

    loaded_document = storage.get_document(document.id)
    loaded_section = storage.get_section(section.id)
    assert loaded_document is not None and loaded_document.metadata["kind"] == "test"
    assert loaded_section is not None and loaded_section.verbatim_content == "Original text"
    assert storage.list_artifacts(document.id)[0].grounding == artifact.grounding
    assert storage.list_messages(thread.id)[0].content == message.content
    assert storage.get_or_create_root_thread(document.id, section.id).id == thread.id


def test_clean_ai_generated_content_preserves_sources(tmp_path):
    storage = StorageService(data_dir=tmp_path / "data")
    source_path, digest = storage.save_pasted_source("Original text", ".txt")
    document = storage.create_document("Doc", "pasted", source_path, digest)
    section = storage.create_section(
        Section(
            id=new_id("sec"),
            document_id=document.id,
            title="Intro",
            verbatim_content="Original text",
            ai_summary="Generated summary",
        )
    )
    generated_doc, _sections = storage.create_generated_document(
        "AI Generated",
        "# Generated\n\nOriginal text grounded synthesis.",
        [{"section_id": section.id}],
    )
    generated_path = generated_doc.source_path
    storage.create_artifact(
        AIArtifact(
            document_id=document.id,
            section_id=section.id,
            artifact_type="summary",
            content="Generated summary",
            model="fallback-local",
            prompt_version="test",
        )
    )
    storage.create_scratchpad(AgentScratchpad(kind="dream", document_id=document.id, section_id=section.id))
    storage.create_research_fragment(ResearchFragment(title="Idea", content="Generated idea", document_id=document.id))
    thread = storage.get_or_create_root_thread(document.id, section.id)
    storage.create_message(DiscussionMessage(thread_id=thread.id, actor="user", content="Keep me"))
    storage.create_message(DiscussionMessage(thread_id=thread.id, actor="expert_agent", content="Remove me"))
    storage.save_embedding("section", section.id, "hash", "fallback-local", [0.1])

    counts = storage.clean_ai_generated_content()

    assert counts["ai_documents"] == 1
    assert counts["artifact_files"] == 1
    assert storage.get_document(document.id) is not None
    assert storage.get_document(generated_doc.id) is None
    assert generated_path is not None and not Path(generated_path).exists()
    cleaned_section = storage.get_section(section.id)
    assert cleaned_section is not None
    assert cleaned_section.verbatim_content == "Original text"
    assert cleaned_section.ai_summary == ""
    assert storage.list_artifacts(document.id) == []
    assert storage.list_scratchpads() == []
    assert storage.list_research_fragments(status=None) == []
    messages = storage.list_messages(thread.id)
    assert [message.actor for message in messages] == ["user"]
    assert storage.list_embeddings() == []
