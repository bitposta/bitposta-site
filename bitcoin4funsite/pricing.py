"""Exact, offline Bitcoin amount conversion and envelope pricing."""

import re
from decimal import Context, Decimal, InvalidOperation, ROUND_CEILING, localcontext

SATOSHIS_PER_BTC = 100_000_000
MAX_SATOSHIS = 21_000_000 * SATOSHIS_PER_BTC

# The operator's own all-in acquisition cost is 3.5%: buying bitcoin costs more
# than the quoted market price, and the owner prices that whole chain as one
# number. The markup is applied ONCE, to the rate; the principal is never
# charged a second percentage fee, and there is no separate fixed acquisition
# fee any more — the two flat charges were removed from the model.
EXCHANGE_FEE = Decimal("0.035")
# The operator's fee on the whole order subtotal.
OPERATOR_FEE = Decimal("0.05")


def btc_to_sats(text: str) -> int:
    """Convert unsigned ASCII BTC text (at most eight decimals), without rounding.

    Whitespace, signs, scientific notation, text over 64 characters and amounts
    above 21 million BTC raise ValueError. Zero is valid; no normalization.
    """
    if (not isinstance(text, str) or len(text) > 64
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,8})?", text)):
        raise ValueError("BTC must be unsigned ASCII decimal text, at most 64 characters and 8 decimals")
    amount = Decimal(text)
    if amount > Decimal("21000000"):
        raise ValueError("BTC exceeds the 21 million supply limit")
    with localcontext(Context(prec=32)):
        return int(amount * SATOSHIS_PER_BTC)


def sats_to_btc(value: int | str) -> str:
    """Format unsigned satoshis as BTC with eight decimals, without rounding.

    Accept an int (not bool) or <=64 ASCII digits in the supply range.
    All invalid inputs raise ValueError.
    """
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError("Satoshis must be an integer or unsigned ASCII digit string")
    if isinstance(value, str) and (len(value) > 64 or not re.fullmatch(r"[0-9]+", value)):
        raise ValueError("Satoshis must be unsigned ASCII digits, at most 64 characters")
    amount = Decimal(value)
    if not 0 <= amount <= MAX_SATOSHIS:
        raise ValueError("Satoshis must be within the 21 million BTC supply limit")
    with localcontext(Context(prec=32)):
        return format(amount / SATOSHIS_PER_BTC, ".8f")


def _decimal_text(value: Decimal) -> str:
    """Render JSON-safe non-exponential decimal text without redundant zeros."""
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _ceil(value: Decimal) -> int:
    return int(value.to_integral_value(rounding=ROUND_CEILING))


def _quote_row(principal: int, network: int, materials: int, post: int,
               satoshi_toman: Decimal, budget: int | None = None, tag: int = 0,
               envelope: int = 0, quantity: int = 1) -> dict:
    # The 3.5% acquisition markup already lives in satoshi_toman, so the
    # principal is charged exactly once.
    #
    # Three cost groups, and the owner's distinction is the whole point:
    #   card   — spent per paper card: the principal, the delivery network fee,
    #            the print/seal materials and the NFC tag.
    #   shared — spent ONCE per order: the postal envelope and the postage.
    # print_materials_sats names group 2 (materials + tag) and post_total_sats
    # names group 3 (envelope + post), so the page shows the groups without
    # re-adding components. With no fixed acquisition fees left, the per-order
    # block IS the postal group, so shared_sats and post_total_sats are equal by
    # construction; shared_sats keeps the per-order meaning for the quantity
    # arithmetic and shared_share_sats.
    # principal is the amount on ONE card; quantity multiplies the card group.
    card_sats = principal + network + materials + tag
    shared_sats = envelope + post
    subtotal = card_sats * quantity + shared_sats
    operator = _ceil(OPERATOR_FEE * subtotal)
    total_sats = subtotal + operator
    total_toman = _ceil(total_sats * satoshi_toman)
    # The operator's income in toman: the same 5% fee, converted at the same rate and
    # rounded up once. Never recomputed from total_toman, which would double the ceiling.
    operator_toman = _ceil(operator * satoshi_toman)
    # The per-card share of the shared block, rounded UP so a row never under-states
    # what the buyer pays. This is what the table shows so orders of different
    # sizes are comparable; it is NOT charged again per card.
    shared_share_sats = -(-shared_sats // quantity)
    return {
        "principal_sats": principal, "btc": sats_to_btc(principal),
        "quantity": quantity,
        "network_sats": network,
        "materials_sats": materials,
        "envelope_sats": envelope, "post_sats": post,
        "tag_sats": tag,
        "print_materials_sats": materials + tag,
        "post_total_sats": envelope + post,
        "card_sats": card_sats, "shared_sats": shared_sats,
        "shared_share_sats": shared_share_sats,
        "operator_sats": operator, "operator_toman": operator_toman, "total_sats": total_sats,
        "total_toman": total_toman, "total_rial": total_toman * 10,
        "budget_toman": budget,
        "remainder_toman": 0 if budget is None else budget - total_toman,
    }


def _rate(value, maximum: Decimal, name: str) -> Decimal:
    """Validate exact decimal rates, bounded to 18 fractional places."""
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{name} must be decimal text, int or Decimal (not float/bool)")
    if isinstance(value, str) and (
        len(value) > 64
        or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,18})?", value)
    ):
        raise ValueError(f"{name} must be unsigned ASCII decimal text, at most 18 decimals")
    try:
        amount = Decimal(value)
    except InvalidOperation as error:
        raise ValueError(f"{name} must be a finite decimal") from error
    if not amount.is_finite() or not 0 < amount <= maximum:
        raise ValueError(f"{name} must be positive and no greater than {maximum}")
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or not -18 <= exponent <= 0:
        raise ValueError(f"{name} must have at most 18 fractional places and no positive exponent")
    return amount


def _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag=False,
                    in_person=False, has_wallet=False):
    """Prepare the shared adjusted rates and fixed costs in a private context."""
    for name, value in (("include_tag", include_tag), ("in_person", in_person),
                        ("has_wallet", has_wallet)):
        if type(value) is not bool:
            raise ValueError(f"{name} must be a boolean")
    raw_btc = _rate(btc_toman, Decimal("1e15"), "btc_toman")
    raw_usdt = _rate(usdt_toman, Decimal("1e15"), "usdt_toman")
    rate = _rate(fee_rate, Decimal("10000"), "fee_rate")
    with localcontext(Context(prec=128)):
        adjusted_btc = raw_btc * (1 + EXCHANGE_FEE)
        adjusted_usdt = raw_usdt
        satoshi_toman = adjusted_btc / SATOSHIS_PER_BTC
        network_sats = _ceil(rate * 141)
        # Group 2 — print, wax seal and the optional NFC label. It is spent on
        # the card itself, so it is always charged: $0.03 seal + $0.01 paper
        # + $0.01 print = $0.05, plus $0.12 for the label when it is chosen.
        # A buyer who already has a wallet gets no card, so the whole group is
        # zero for them.
        materials_sats = (0 if has_wallet
                          else _ceil(Decimal("0.05") * adjusted_usdt / satoshi_toman))
        # Group 3 — the postal envelope and the postage, charged once per order.
        # Hand delivery drops both because nothing is mailed; so does a buyer
        # who already has a wallet, because there is no card to put in it.
        mailed = not (in_person or has_wallet)
        envelope_sats = _ceil(Decimal("0.06") * adjusted_usdt / satoshi_toman) if mailed else 0
        post_sats = _ceil(Decimal("0.75") * adjusted_usdt / satoshi_toman) if mailed else 0
        tag_sats = (0 if has_wallet or not include_tag
                    else _ceil(Decimal("0.12") * adjusted_usdt / satoshi_toman))
        metadata = {
            "rates": {
                "btc_toman": _decimal_text(adjusted_btc),
                "usdt_toman": _decimal_text(adjusted_usdt),
                "satoshi_toman": _decimal_text(satoshi_toman),
            },
            "assumptions": {
                "exchange_fee_percent": "3.5", "operator_fee_percent": "5",
                "materials_usd": "0.05", "envelope_usd": "0.06", "post_usd": "0.75",
                "tag_usd": "0.12", "include_tag": include_tag,
                "in_person": in_person, "has_wallet": has_wallet,
                "transaction_vbytes": 141,
                "network_fee_rate": _decimal_text(rate),
                "seal_usd": "0.03", "paper_usd": "0.01", "print_usd": "0.01",
            },
            "costs": {"network_sats": network_sats,
                      "materials_sats": materials_sats,
                      "envelope_sats": envelope_sats, "post_sats": post_sats,
                      "tag_sats": tag_sats,
                      "print_materials_sats": materials_sats + tag_sats,
                      "post_total_sats": envelope_sats + post_sats},
        }
    return (satoshi_toman, network_sats, materials_sats, envelope_sats, post_sats,
            tag_sats, metadata)


def _unsigned_integer(value, name: str, minimum: int, maximum: int) -> int:
    """Parse a bounded integer without normalizing signs, spaces or exponents."""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError(f"{name} must be an int or unsigned ASCII digit string")
    if isinstance(value, str):
        if len(value) > 64 or not re.fullmatch(r"[0-9]+", value):
            raise ValueError(f"{name} must be unsigned ASCII digits, at most 64 characters")
        value = int(value)
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def raw_asset_toman(raw_btc, principal_sats) -> str:
    """Exact raw BTC asset value in toman as decimal text, without any fees.

    The rate follows quote_table validation, before its 3.5% acquisition markup.
    Principal is an int or <=64 ASCII digits in [0, MAX_SATOSHIS]; zero and
    sub-package amounts are valid. No currency rounding is applied.
    """
    raw = _rate(raw_btc, Decimal("1e15"), "raw_btc")
    principal = _unsigned_integer(principal_sats, "principal_sats", 0, MAX_SATOSHIS)
    with localcontext(Context(prec=128)):
        return _decimal_text(raw * principal / SATOSHIS_PER_BTC)


def _quantity(value, name: str = "quantity") -> int:
    """Parse the number of cards in one order: a plain int in [1, 100]."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("quantity must be an integer")
    if not 1 <= value <= 100:
        raise ValueError("quantity must be between 1 and 100")
    return value


def quote_for_principal(btc_toman, usdt_toman, fee_rate, principal_sats, *,
                        include_tag=False, in_person=False, has_wallet=False,
                        quantity=1) -> dict:
    """Quote one supply-bounded package; row fields keep the v1 numeric types.

    The returned row also includes the table's rates, assumptions and costs.
    Rates follow quote_table. Principal accepts int (not bool) or unsigned ASCII
    digits, at most 64 characters, in [501, MAX_SATOSHIS]. Otherwise ValueError.
    in_person drops the postal envelope and the postage, because the buyer
    collects the card by hand. has_wallet drops the print/seal/label group AND
    the postal group, because no card is made or mailed: the bitcoin simply goes
    to the buyer's own address. The network fee stays, because the operator
    still sends the transaction.
    quantity is the number of identical cards in ONE order (an int in [1, 100],
    default 1). It multiplies only the card-bound costs — the principal, the
    delivery network fee, the print/seal materials and the tag. The postal
    envelope and the postage are paid once per order, so they are NOT
    multiplied: five cards cost less than five orders.
    shared_share_sats is the per-card share of that shared block, so a row can
    state what one card effectively carries.
    """
    principal = _unsigned_integer(principal_sats, "principal_sats", 501, MAX_SATOSHIS)
    cards = _quantity(quantity)
    (satoshi_toman, network, materials, envelope, post, tag,
     metadata) = _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag,
                                 in_person, has_wallet)
    with localcontext(Context(prec=128)):
        row = _quote_row(principal, network, materials, post, satoshi_toman, tag=tag,
                         envelope=envelope, quantity=cards)
    return {**row, **metadata}


def quote_for_budget(btc_toman, usdt_toman, fee_rate, budget_toman, *,
                     include_tag=False, in_person=False, has_wallet=False,
                     quantity=1) -> dict:
    """Return the largest principal in [501, MAX_SATOSHIS] fitting the budget.

    Budget is a whole toman amount: int (not bool) or unsigned ASCII digits,
    at most 64 digits. There is no table cap here; the 3,000,000-toman ceiling
    belongs to quote_table only. If 501 satoshis cannot be afforded, ValueError
    is raised (no fictitious principal or row). Successful rows include
    rates/assumptions/costs and the unspent remainder.
    in_person drops the postal envelope and the postage; has_wallet drops the
    print/seal/label group and the postal group as well.
    quantity multiplies only the card-bound costs (see quote_for_principal), so
    the postal charges are paid once for the whole order.
    """
    budget = _unsigned_integer(budget_toman, "budget_toman", 0, 10**64 - 1)
    cards = _quantity(quantity)
    (satoshi_toman, network, materials, envelope, post, tag,
     metadata) = _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag,
                                 in_person, has_wallet)
    with localcontext(Context(prec=128)):
        minimum = _quote_row(501, network, materials, post, satoshi_toman, tag=tag,
                             envelope=envelope, quantity=cards)
        if minimum["total_toman"] > budget:
            raise ValueError(
                f"budget_toman insufficient for minimum 501-satoshi package; "
                f"requires {minimum['total_toman']} toman"
            )
        low, high = 501, MAX_SATOSHIS
        while low < high:
            middle = (low + high + 1) // 2
            candidate = _quote_row(middle, network, materials, post, satoshi_toman, tag=tag,
                                   envelope=envelope, quantity=cards)
            if candidate["total_toman"] <= budget:
                low = middle
            else:
                high = middle - 1
        row = _quote_row(low, network, materials, post, satoshi_toman, budget, tag=tag,
                         envelope=envelope, quantity=cards)
    return {**row, **metadata}


def quote_table(btc_toman, usdt_toman, fee_rate, *, include_tag=False,
                in_person=False, has_wallet=False, quantity=1) -> dict:
    """Return an offline quote using the selected fee in sat/vbyte.

    Rates accept int, Decimal or unsigned ASCII decimal text, never float/bool.
    Raw prices are positive and <= 1e15 toman; fee is positive and <= 10,000
    sat/vbyte. Rates have at most 18 decimal places (minimum positive 1e-18).
    Malformed/out-of-bounds inputs raise ValueError. The three option flags must
    be bool and default to False.

    Both raw prices are used as received. The bitcoin rate carries the owner's
    3.5% acquisition markup, because that is the all-in cost of buying the coin
    and turning it into bitcoin. The markup is applied ONCE, to the rate; the
    principal is never charged a second percentage fee, and the two old flat
    acquisition fees (a two-cent conversion charge and a 423-satoshi transfer)
    no longer exist in this model. The tether rate is NOT marked up, because the
    dollar costs are already divided by the marked-up satoshi price, so a markup
    on both sides would cancel out.
    Every following ceiling is explicit (no intermediate currency rounding):
      network_sats = ceil(fee_rate * 141)
      materials_sats = 0 if has_wallet else ceil(0.05 * usdt_toman / satoshi_toman)
      envelope_sats = 0 if in_person or has_wallet else ceil(0.06 * usdt_toman / satoshi_toman)
      post_sats = 0 if in_person or has_wallet else ceil(0.75 * usdt_toman / satoshi_toman)
      tag_sats = 0 if has_wallet or not include_tag else ceil(0.12 * usdt_toman / satoshi_toman)
      print_materials_sats = materials_sats + tag_sats
      post_total_sats = envelope_sats + post_sats
      operator_sats = ceil(0.05 * (card_sats * quantity + shared_sats))
      operator_toman = ceil(operator_sats * satoshi_toman)
      total_toman = ceil((card_sats * quantity + shared_sats + operator_sats) * satoshi_toman)
      total_rial = total_toman * 10
    operator_toman is the operator's income for that row: the same 5% fee
    converted to toman and rounded up once. It is derived from operator_sats,
    never from total_toman, so the two ceilings are not applied twice.
    The 0.05 USD materials charge is the wax seal, the paper and the printing,
    and it is always spent on the card itself. Postal delivery adds two separate
    charges: a 0.06 USD envelope and 0.75 USD postage. in_person=True drops only
    those two, because the buyer collects the card by hand; materials, the tag
    charge and the network fee are unaffected.
    has_wallet=True is a different choice: the buyer already has a wallet, so no
    card is printed, sealed or labelled and nothing is mailed. Both the
    print/seal/label group and the postal group become zero. The principal, the
    operator fee and the network fee remain, because the bitcoin still has to
    reach the buyer's own address.
    network_sats is the separate delivery transaction from the operator's own
    wallet to the paper wallet (or to the buyer's address), and it is the only
    cost the speed selector moves.
    The 141 vB estimate assumes one P2WPKH input and two P2WPKH outputs.
    A first 501-satoshi quote is always shown, even above 3,000,000 toman.
    Budget rows begin at the next strictly greater 100,000-toman multiple;
    binary search finds the largest supply-bounded principal that fits each
    ceiling. Remainder is budget minus actual rounded cost (zero without a
    budget); it is never hidden by pretending the whole budget was spent.
    quantity is the number of identical cards in ONE order (an int in [1, 100],
    default 1). Only the card-bound costs are multiplied — the principal, the
    delivery network fee, the print/seal materials and the tag. The postal
    envelope and the postage are paid ONCE per order, so five cards cost less
    than five separate orders.
    """
    (satoshi_toman, network_sats, materials_sats, envelope_sats, post_sats, tag,
     metadata) = _pricing_inputs(btc_toman, usdt_toman, fee_rate, include_tag,
                                 in_person, has_wallet)
    cards = _quantity(quantity)
    with localcontext(Context(prec=128)):
        def build(principal, budget=None):
            return _quote_row(principal, network_sats, materials_sats, post_sats, satoshi_toman,
                              budget, tag=tag, envelope=envelope_sats,
                              quantity=cards)

        first = build(501)
        rows = [first]
        first_budget = (first["total_toman"] // 100_000 + 1) * 100_000
        for budget in range(first_budget, 3_000_001, 100_000):
            low, high = 501, MAX_SATOSHIS
            while low < high:
                middle = (low + high + 1) // 2
                if build(middle)["total_toman"] <= budget:
                    low = middle
                else:
                    high = middle - 1
            rows.append(build(low, budget))
        # quantity and the shared block are per ORDER, not per row, so they sit at
        # the top level beside costs. rows[].shared_share_sats carries the per-card
        # share of the same block.
        return {**metadata, "quantity": cards,
                "shared_sats": rows[0]["shared_sats"],
                "shared_share_sats": rows[0]["shared_share_sats"],
                "card_sats": rows[0]["card_sats"],
                "rows": rows}
