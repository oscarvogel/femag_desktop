from app.models.audit import AuditLog
from app.models.accounting import ClientAccountMovement
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
from app.models.load_orders import (
    LoadOrder,
    LoadOrderDestination,
    LoadOrderPallet,
    LoadOrderProduct,
    LoadOrderStatusHistory,
)
from app.models.security import MenuItem, Permission, User, UserProfile
from app.models.system import AppParameter, BackupLog, ImportBatch, NumberSequence


ALL_MODELS = [
    UserProfile,
    User,
    MenuItem,
    Permission,
    AuditLog,
    ClientAccountMovement,
    Client,
    ClientAddress,
    Product,
    Carrier,
    Driver,
    Truck,
    PalletType,
    OperationalService,
    LoadOrder,
    LoadOrderDestination,
    LoadOrderProduct,
    LoadOrderPallet,
    LoadOrderStatusHistory,
    AppParameter,
    NumberSequence,
    ImportBatch,
    BackupLog,
]
