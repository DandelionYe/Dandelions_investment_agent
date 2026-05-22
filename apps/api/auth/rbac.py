"""RBAC helper — 统一权限判断语义。

角色定义：
- admin: 可跨用户访问所有资源，可管理用户。
- user:  只能访问自己拥有的资源。

资源 owner 字段：
- research_tasks.created_by
- watchlist_folders.owner_username
- watchlist_items.owner_username
- watchlist_tags.owner_username
- watchlist_batches.owner_username
- reports 通过 task.created_by 间接授权
"""


def is_admin(user: dict) -> bool:
    """判断用户是否为管理员。"""
    return user.get("role") == "admin"


def scope_username(user: dict) -> str | None:
    """返回用户的作用域用户名。

    普通用户返回自己的 username（用于 owner 过滤）。
    管理员返回 None（表示可访问全部）。
    """
    if is_admin(user):
        return None
    return user.get("username")


def require_owner_or_admin(user: dict, owner: str) -> None:
    """校验当前用户是否为资源所有者或管理员。

    普通用户访问他人资源时抛出 KeyError（返回 404，避免暴露资源存在性）。
    """
    if is_admin(user):
        return
    if user.get("username") != owner:
        raise KeyError("资源不存在")
