import pytest

from fta_agent.core.registry import Registry, RegistryError


def test_register_and_create():
    reg = Registry("test")

    @reg.register("foo")
    class Foo:
        def __init__(self, x=1):
            self.x = x

    assert "foo" in reg
    obj = reg.create("foo", x=42)
    assert isinstance(obj, Foo)
    assert obj.x == 42


def test_unknown_key_lists_available():
    reg = Registry("test")

    @reg.register("known")
    class Known:
        pass

    with pytest.raises(RegistryError, match="known"):
        reg.create("unknown")


def test_duplicate_registration_rejected():
    reg = Registry("test")

    @reg.register("dup")
    class A:
        pass

    with pytest.raises(RegistryError):
        @reg.register("dup")
        class B:
            pass
