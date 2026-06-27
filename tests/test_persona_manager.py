import time
import pytest

from core.db.db_mgr import DatabaseManager
from core.db.service import DatabaseService
from core.persona.persona_manager import PersonaManager
from core.persona.model import PersonaInfo


@pytest.fixture
async def persona_manager():
    """Create a fresh PersonaManager with in-memory database."""
    manager = DatabaseManager("sqlite+aiosqlite:///:memory:")
    await manager.init()
    service = DatabaseService(manager)
    await service.init_tables()
    pm = PersonaManager(db=service)
    yield pm
    await manager.dispose()


@pytest.mark.anyio
async def test_create_persona(persona_manager):
    """Test creating a new persona."""
    persona = PersonaInfo(
        id="test-1",
        name="Test Persona",
        format="text",
        content="Hello, I am a test persona.",
        created_at=int(time.time()),
        is_active=False
    )
    result = await persona_manager.create_persona(persona)
    assert result is True

    # Verify it was created
    retrieved = await persona_manager.get_persona("test-1")
    assert retrieved is not None
    assert retrieved.id == "test-1"
    assert retrieved.name == "Test Persona"
    assert retrieved.format == "text"
    assert retrieved.content == "Hello, I am a test persona."


@pytest.mark.anyio
async def test_get_persona_by_id(persona_manager):
    """Test getting a specific persona by ID."""
    # Create two personas
    persona1 = PersonaInfo(id="p1", name="Persona 1", content="Content 1")
    persona2 = PersonaInfo(id="p2", name="Persona 2", content="Content 2")
    await persona_manager.create_persona(persona1)
    await persona_manager.create_persona(persona2)

    # Get by ID
    result = await persona_manager.get_persona("p1")
    assert result is not None
    assert result.id == "p1"
    assert result.name == "Persona 1"

    result = await persona_manager.get_persona("p2")
    assert result is not None
    assert result.id == "p2"

    # Non-existent
    result = await persona_manager.get_persona("non-existent")
    assert result is None


@pytest.mark.anyio
async def test_get_active_persona(persona_manager):
    """Test getting the currently active persona."""
    # Create personas
    persona1 = PersonaInfo(id="p1", name="Persona 1", content="Content 1")
    persona2 = PersonaInfo(id="p2", name="Persona 2", content="Content 2")
    await persona_manager.create_persona(persona1)
    await persona_manager.create_persona(persona2)

    # Initially no active persona
    active = await persona_manager.get_active_persona()
    assert active is None

    # Set p1 as active
    result = await persona_manager.set_active_persona("p1")
    assert result is True

    active = await persona_manager.get_active_persona()
    assert active is not None
    assert active.id == "p1"
    assert active.is_active is True


@pytest.mark.anyio
async def test_set_active_persona(persona_manager):
    """Test switching the active persona."""
    # Create personas
    persona1 = PersonaInfo(id="p1", name="Persona 1", content="Content 1")
    persona2 = PersonaInfo(id="p2", name="Persona 2", content="Content 2")
    await persona_manager.create_persona(persona1)
    await persona_manager.create_persona(persona2)

    # Set p1 as active
    await persona_manager.set_active_persona("p1")
    active = await persona_manager.get_active_persona()
    assert active.id == "p1"

    # Switch to p2
    result = await persona_manager.set_active_persona("p2")
    assert result is True

    active = await persona_manager.get_active_persona()
    assert active.id == "p2"
    assert active.is_active is True

    # Verify p1 is no longer active
    p1 = await persona_manager.get_persona("p1")
    assert p1.is_active is False


@pytest.mark.anyio
async def test_set_active_persona_non_existent(persona_manager):
    """Test setting a non-existent persona as active."""
    result = await persona_manager.set_active_persona("non-existent")
    assert result is False


@pytest.mark.anyio
async def test_list_personas(persona_manager):
    """Test listing all personas."""
    # Initially empty
    personas = await persona_manager.list_personas()
    assert len(personas) == 0

    # Create personas
    persona1 = PersonaInfo(id="p1", name="Persona 1", content="Content 1")
    persona2 = PersonaInfo(id="p2", name="Persona 2", content="Content 2")
    persona3 = PersonaInfo(id="p3", name="Persona 3", content="Content 3")
    await persona_manager.create_persona(persona1)
    await persona_manager.create_persona(persona2)
    await persona_manager.create_persona(persona3)

    # List should have 3 personas
    personas = await persona_manager.list_personas()
    assert len(personas) == 3
    assert all(isinstance(p, PersonaInfo) for p in personas)
    ids = {p.id for p in personas}
    assert ids == {"p1", "p2", "p3"}


@pytest.mark.anyio
async def test_update_persona(persona_manager):
    """Test updating a persona."""
    # Create a persona
    persona = PersonaInfo(id="p1", name="Original Name", content="Original content", format="text")
    await persona_manager.create_persona(persona)

    # Update it
    updated_persona = PersonaInfo(
        id="p1",
        name="Updated Name",
        content="Updated content",
        format="markdown",
        is_active=True
    )
    result = await persona_manager.update_persona(updated_persona)
    assert result is True

    # Verify changes
    retrieved = await persona_manager.get_persona("p1")
    assert retrieved.name == "Updated Name"
    assert retrieved.content == "Updated content"
    assert retrieved.format == "markdown"
    assert retrieved.is_active is True


@pytest.mark.anyio
async def test_delete_persona(persona_manager):
    """Test deleting a persona."""
    # Create a persona
    persona = PersonaInfo(id="p1", name="Persona 1", content="Content 1")
    await persona_manager.create_persona(persona)

    # Verify it exists
    retrieved = await persona_manager.get_persona("p1")
    assert retrieved is not None

    # Delete it
    result = await persona_manager.delete_persona("p1")
    assert result is True

    # Verify it's gone
    retrieved = await persona_manager.get_persona("p1")
    assert retrieved is None

    # Delete non-existent
    result = await persona_manager.delete_persona("non-existent")
    assert result is False


@pytest.mark.anyio
async def test_delete_active_persona_fails(persona_manager):
    """Test that deleting an active persona raises an error."""
    # Create personas
    persona1 = PersonaInfo(id="p1", name="Persona 1", content="Content 1")
    persona2 = PersonaInfo(id="p2", name="Persona 2", content="Content 2")
    await persona_manager.create_persona(persona1)
    await persona_manager.create_persona(persona2)

    # Set p1 as active
    await persona_manager.set_active_persona("p1")

    # Try to delete active persona - should raise ValueError
    with pytest.raises(ValueError, match="Cannot delete the active persona"):
        await persona_manager.delete_persona("p1")

    # Verify it still exists
    retrieved = await persona_manager.get_persona("p1")
    assert retrieved is not None

    # Switch to p2 and try to delete p1 - should succeed
    await persona_manager.set_active_persona("p2")
    result = await persona_manager.delete_persona("p1")
    assert result is True

    # Verify p1 is gone
    retrieved = await persona_manager.get_persona("p1")
    assert retrieved is None


@pytest.mark.anyio
async def test_init_persona(persona_manager):
    """Test initializing default persona."""
    # Initially no personas
    personas = await persona_manager.list_personas()
    assert len(personas) == 0

    # Initialize
    await persona_manager.init_persona()

    # Should have created default persona
    personas = await persona_manager.list_personas()
    assert len(personas) == 1
    assert personas[0].id == "default"
    assert personas[0].name == "Default"
    assert personas[0].is_active is True

    # Calling init again should not create duplicates
    await persona_manager.init_persona()
    personas = await persona_manager.list_personas()
    assert len(personas) == 1


@pytest.mark.anyio
async def test_get_persona_returns_none_when_no_active(persona_manager):
    """Test that get_persona returns None when no persona is active."""
    # Create default persona but do not activate it
    default = PersonaInfo(id="default", name="Default", content="Default content")
    await persona_manager.create_persona(default)

    # No active persona, should return None
    persona = await persona_manager.get_persona()
    assert persona is None


@pytest.mark.anyio
async def test_wrap_persona():
    """Test wrap_persona static method."""
    persona_dict = {
        "id": "test-id",
        "name": "Test Name",
        "format": "yaml",
        "content": "Test content",
        "created_at": 1234567890,
        "is_active": True
    }

    persona = PersonaManager.wrap_persona(persona_dict)
    assert isinstance(persona, PersonaInfo)
    assert persona.id == "test-id"
    assert persona.name == "Test Name"
    assert persona.format == "yaml"
    assert persona.content == "Test content"
    assert persona.created_at == 1234567890
    assert persona.is_active is True

    # Test with missing optional fields
    persona_dict_minimal = {"id": "minimal"}
    persona_minimal = PersonaManager.wrap_persona(persona_dict_minimal)
    assert persona_minimal.id == "minimal"
    assert persona_minimal.name is None
    assert persona_minimal.format is None
    assert persona_minimal.content is None
    assert persona_minimal.created_at is None
    assert persona_minimal.is_active is False


@pytest.mark.anyio
async def test_multiple_active_personas(persona_manager):
    """Test that only one persona can be active at a time."""
    # Create personas
    persona1 = PersonaInfo(id="p1", name="Persona 1", content="Content 1")
    persona2 = PersonaInfo(id="p2", name="Persona 2", content="Content 2")
    persona3 = PersonaInfo(id="p3", name="Persona 3", content="Content 3")
    await persona_manager.create_persona(persona1)
    await persona_manager.create_persona(persona2)
    await persona_manager.create_persona(persona3)

    # Set p1 as active
    await persona_manager.set_active_persona("p1")
    active = await persona_manager.get_active_persona()
    assert active.id == "p1"

    # Set p2 as active - p1 should be deactivated
    await persona_manager.set_active_persona("p2")
    active = await persona_manager.get_active_persona()
    assert active.id == "p2"

    # Set p3 as active - p2 should be deactivated
    await persona_manager.set_active_persona("p3")
    active = await persona_manager.get_active_persona()
    assert active.id == "p3"

    # Verify only p3 is active
    personas = await persona_manager.list_personas()
    active_personas = [p for p in personas if p.is_active]
    assert len(active_personas) == 1
    assert active_personas[0].id == "p3"
