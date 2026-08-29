def test_aviso_service_count_unread_initially_zero(db):
    from app.models.security import User, UserProfile
    from app.services.permission_service import PermissionService
    from app.services.aviso_service import AvisoService

    PermissionService().seed_defaults()
    profile = UserProfile.get(UserProfile.name == "Administrador")
    user = User.create(username="admin_aviso_infra", password_hash="x", profile=profile)
    svc = AvisoService()
    assert svc.count_unread(user) == 0
    assert svc.get_for_user(user) == []


def test_aviso_orden_sin_cierre_generates_for_secretaria(db, tmp_path):
    from decimal import Decimal

    from app.models.masters import Carrier, Client, ClientAddress, Driver, Product, Truck
    from app.models.security import User, UserProfile
    from app.services.aviso_service import AvisoService
    from app.services.load_order_operation_service import LoadOrderOperationService
    from app.services.load_order_service import LoadOrderService
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()

    # product must not trigger producto_revision: review_required=False and peso >0
    product = Product.create(
        name="Fecula aviso OC",
        unit="kg",
        peso_unitario_kg=Decimal("1.000"),
        review_required=False,
        product_kind="producto",
    )
    carrier = Carrier.create(name="Carrier Aviso", cuit="30777777771")
    driver = Driver.create(name="Driver Aviso", carrier=carrier, document="999")
    truck = Truck.create(domain="AV123CD", carrier=carrier)
    client = Client.create(name="Cliente Aviso", cuit="30712345679", iva_condition="RI")
    address = ClientAddress.create(
        client=client,
        address_type="entrega",
        province="Misiones",
        city="Posadas",
        address="Ruta 12 aviso",
        is_primary=True,
    )

    svc_order = LoadOrderService(current_user="admin")
    order = svc_order.create_order(
        carrier=carrier,
        driver=driver,
        truck=truck,
        destinations=[
            {
                "client": client,
                "delivery_address": address,
                "products": [{"product": product, "quantity": 10}],
            }
        ],
        pallets=[
            {
                "sequence": 1,
                "pallet_type": None,
                "allocations": [
                    {
                        "client": client,
                        "delivery_address": address,
                        "product": product,
                        "quantity": 10,
                    }
                ],
            }
        ],
    )
    LoadOrderOperationService(current_user="admin", prints_dir=tmp_path).issue(order)

    secretaria = UserProfile.get(UserProfile.name == "Secretaría")
    user_sec = User.create(username="sec_aviso", password_hash="x", profile=secretaria)
    svc = AvisoService()
    avisos = svc.get_for_user(user_sec)
    assert any(a.tipo == "orden_sin_cierre" for a in avisos), f"expected orden_sin_cierre in {avisos}"
    # gerencia should not see orden_sin_cierre
    gerencia = UserProfile.get(UserProfile.name == "Gerencia")
    user_ger = User.create(username="ger_aviso", password_hash="x", profile=gerencia)
    avisos_ger = svc.get_for_user(user_ger)
    assert not any(a.tipo == "orden_sin_cierre" for a in avisos_ger)


def test_aviso_producto_revision_visible_para_administracion(db):
    from decimal import Decimal

    from app.models.masters import Product
    from app.models.security import User, UserProfile
    from app.services.aviso_service import AvisoService
    from app.services.permission_service import PermissionService

    PermissionService().seed_defaults()

    # product with review_required True triggers aviso
    Product.create(
        name="Prod Revision Aviso",
        unit="kg",
        peso_unitario_kg=Decimal("0.000"),
        review_required=True,
        product_kind="producto",
    )
    # also producto with peso 0 and review_required False should trigger
    Product.create(
        name="Prod Peso Cero",
        unit="kg",
        peso_unitario_kg=Decimal("0.000"),
        review_required=False,
        product_kind="producto",
    )

    administracion = UserProfile.get(UserProfile.name == "Administración")
    user_admin = User.create(username="adm_aviso", password_hash="x", profile=administracion)
    svc = AvisoService()
    avisos_admin = svc.get_for_user(user_admin)
    assert any(a.tipo == "producto_revision" for a in avisos_admin), f"expected producto_revision for administracion in {avisos_admin}"

    # gerencia should not see producto_revision
    gerencia = UserProfile.get(UserProfile.name == "Gerencia")
    user_ger = User.create(username="ger_aviso_prod", password_hash="x", profile=gerencia)
    avisos_ger = svc.get_for_user(user_ger)
    assert not any(a.tipo == "producto_revision" for a in avisos_ger)

    # secretaria should not see producto_revision
    secretaria = UserProfile.get(UserProfile.name == "Secretaría")
    user_sec = User.create(username="sec_aviso_prod", password_hash="x", profile=secretaria)
    avisos_sec = svc.get_for_user(user_sec)
    assert not any(a.tipo == "producto_revision" for a in avisos_sec)

    # administrador should see it
    administrador = UserProfile.get(UserProfile.name == "Administrador")
    user_adm = User.create(username="admin_aviso_prod", password_hash="x", profile=administrador)
    avisos_adm = svc.get_for_user(user_adm)
    assert any(a.tipo == "producto_revision" for a in avisos_adm)
