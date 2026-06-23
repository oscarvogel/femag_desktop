from peewee import BooleanField, CharField, ForeignKeyField, IntegerField, TextField

from app.models.base import BaseModel


class UserProfile(BaseModel):
    name = CharField(unique=True)
    description = TextField(null=True)


class User(BaseModel):
    username = CharField(unique=True)
    password_hash = CharField()
    profile = ForeignKeyField(UserProfile, backref="users")
    active = BooleanField(default=True)


class MenuItem(BaseModel):
    parent = ForeignKeyField("self", backref="children", null=True)
    section = CharField(null=True)
    title = CharField()
    icon = CharField(null=True)
    action_key = CharField(null=True, unique=True)
    route_key = CharField(null=True)
    module = CharField(null=True)
    sort_order = IntegerField(default=0)
    is_active = BooleanField(default=True)
    is_placeholder = BooleanField(default=False)
    requires_permission = BooleanField(default=True)

    class Meta:
        indexes = (
            (("parent", "title"), True),
            (("section", "title"), False),
        )


class Permission(BaseModel):
    profile = ForeignKeyField(UserProfile, backref="permissions")
    menu_item = ForeignKeyField(MenuItem, backref="permissions")
    action = CharField()
    allowed = BooleanField(default=True)

    class Meta:
        indexes = ((("profile", "menu_item", "action"), True),)
