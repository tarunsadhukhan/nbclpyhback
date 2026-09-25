"""
Target: filter_menus in src/mobileapp/src/permissions/permissions.py — applies
mobile_role_menu_map permissions to the mobile menu tree.

Run: python -m pytest src/mobileapp/tests/test_menu_permissions.py
"""
from src.mobileapp.src.permissions.permissions import filter_menus

MENUS = [
    {"menu_id": 7, "parent_id": None, "is_group": 1},   # Attendance group
    {"menu_id": 8, "parent_id": 7, "is_group": 0},
    {"menu_id": 9, "parent_id": 7, "is_group": 0},
    {"menu_id": 50, "parent_id": None, "is_group": 1},  # empty group
]


def test_unconfigured_tenant_gets_everything():
    out = filter_menus(MENUS, None)
    assert [m["menu_id"] for m in out] == [7, 8, 9, 50]
    assert all(m["can_all"] == 1 for m in out)


def test_visible_leaf_pulls_in_its_group_only():
    perms = {8: {"can_view": 1, "can_add": 1, "can_modify": 0, "can_delete": 0, "can_print": 0}}
    out = {m["menu_id"]: m for m in filter_menus(MENUS, perms)}
    assert set(out) == {7, 8}
    assert out[8]["can_add"] == 1 and out[8]["can_delete"] == 0 and out[8]["can_all"] == 0
    assert out[7]["can_view"] == 1 and out[7]["can_add"] == 0


def test_no_view_means_hidden_and_no_roles_means_nothing():
    assert filter_menus(MENUS, {9: {"can_view": 0, "can_add": 1}}) == []
    assert filter_menus(MENUS, {}) == []
