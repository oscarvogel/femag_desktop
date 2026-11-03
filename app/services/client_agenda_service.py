from app.models.client_agenda import ClientAgendaEntry


def add_entry(client_id, occurred_on, text, author):
    text = text.strip()
    if not text:
        raise ValueError("Escriba una anotación.")
    return ClientAgendaEntry.create(
        client=client_id, occurred_on=occurred_on, text=text, author=author or ""
    )


def find_entries(client_id, text="", date_from=None, date_to=None):
    if date_from and date_to and date_from > date_to:
        raise ValueError("La fecha desde no puede ser posterior a la fecha hasta.")
    query = ClientAgendaEntry.select().where(ClientAgendaEntry.client == client_id)
    if text.strip():
        query = query.where(ClientAgendaEntry.text.contains(text.strip()))
    if date_from:
        query = query.where(ClientAgendaEntry.occurred_on >= date_from)
    if date_to:
        query = query.where(ClientAgendaEntry.occurred_on <= date_to)
    return list(query.order_by(ClientAgendaEntry.occurred_on.desc(), ClientAgendaEntry.id.desc()))
