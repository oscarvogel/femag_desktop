from app.models.audit import AuditLog
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    Driver,
    OperationalService,
    PalletType,
    Product,
    Truck,
)
from app.models.load_orders import LoadOrder, LoadOrderPallet, LoadOrderProduct, LoadOrderStatusHistory
from app.models.security import MenuItem, Permission, User, UserProfile
from app.models.system import AppParameter, BackupLog, ImportBatch, NumberSequence


ALL_MODELS = [
    UserProfile,
    User,
    MenuItem,
    Permission,
    AuditLog,
    Client,
    ClientAddress,
    Product,
    Carrier,
    Driver,
    Truck,
    PalletType,
    OperationalService,
    LoadOrder,
    LoadOrderProduct,
    LoadOrderPallet,
    LoadOrderStatusHistory,
    AppParameter,
    NumberSequence,
    ImportBatch,
    BackupLog,
]
