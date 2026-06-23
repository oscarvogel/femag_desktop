from peewee import BooleanField, CharField, ForeignKeyField, TextField

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
    section = CharField()
    title = CharField()
    sort_order = CharField(default="000")

    class Meta:
        indexes = ((("section", "title"), True),)


class Permission(BaseModel):
    profile = ForeignKeyField(UserProfile, backref="permissions")
    menu_item = ForeignKeyField(MenuItem, backref="permissions")
    action = CharField()
    allowed = BooleanField(default=True)

    class Meta:
        indexes = ((("profile", "menu_item", "action"), True),)
