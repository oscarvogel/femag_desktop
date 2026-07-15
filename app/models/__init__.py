from app.models.audit import AuditLog
from app.models.payments import ClientPayment
from app.models.accounting import ClientAccountMovement
from app.models.system import AppParameter, BackupLog, ImportBatch, NumberSequence
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    Driver,
    OperationalService,
    PalletType,
    Product,
    TipoIVA,
    Truck,
)
from app.models.load_orders import (
    LoadOrder,
    LoadOrderBudgetStatus,
    LoadOrderDestination,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
    LoadOrderStatusHistory,
)
from app.models.security import MenuItem, Permission, User, UserProfile


ALL_MODELS = [
    UserProfile,
    User,
    MenuItem,
    Permission,
    AuditLog,
    ClientAccountMovement,
    ClientPayment,
    ImportBatch,
    Client,
    ClientAddress,
    Product,
    TipoIVA,
    Carrier,
    Driver,
    Truck,
    PalletType,
    OperationalService,
    LoadOrder,
    LoadOrderDestination,
    LoadOrderProduct,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderStatusHistory,
    LoadOrderBudgetStatus,
    AppParameter,
    NumberSequence,
    BackupLog,
]
