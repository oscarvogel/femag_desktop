from app.models.audit import AuditLog
from app.models.payments import ClientPayment, ClientPaymentDetail, PaymentMethod
from app.models.accounting import ClientAccountMovement
from app.models.system import AppParameter, BackupLog, ImportBatch, NumberSequence
from app.models.masters import (
    Carrier,
    Client,
    ClientAddress,
    ClientEmail,
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
    LoadOrderClosure,
    LoadOrderDestination,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderProduct,
    LoadOrderReturnLine,
    LoadOrderStatusHistory,
)
from app.models.remittances import Remittance, RemittanceItem, RemittanceSeries
from app.models.notifications import AvisoLectura
from app.models.security import MenuItem, Permission, User, UserProfile


ALL_MODELS = [
    UserProfile,
    User,
    MenuItem,
    Permission,
    AuditLog,
    ClientAccountMovement,
    PaymentMethod,
    ClientPayment,
    ClientPaymentDetail,
    ImportBatch,
    Client,
    ClientEmail,
    ClientAddress,
    Product,
    TipoIVA,
    Carrier,
    Truck,
    Driver,
    PalletType,
    OperationalService,
    LoadOrder,
    LoadOrderDestination,
    LoadOrderProduct,
    LoadOrderLooseAllocation,
    LoadOrderPallet,
    LoadOrderPalletAllocation,
    LoadOrderStatusHistory,
    LoadOrderClosure,
    LoadOrderReturnLine,
    LoadOrderBudgetStatus,
    RemittanceSeries,
    Remittance,
    RemittanceItem,
    AppParameter,
    NumberSequence,
    BackupLog,
    AvisoLectura,
]
