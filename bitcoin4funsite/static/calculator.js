"use strict";

(() => {
  const unit = 100000000n;
  const maximum = 2100000000000000n;
  const positiveDecimal = value => typeof value === "string" && value.length <= 48 &&
    /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/.test(value) && /[1-9]/.test(value);
  /** Persian numerals for prose: the site writes counts in Persian digits, never Latin ones. */
  const persianDigits = value => String(value).replace(/[0-9]/g,
    digit => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)]);
  const grouped = value => String(value).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const decimal = value => {
    const parts = value.split(".");
    return grouped(parts[0]) + (parts[1] ? "." + parts[1] : "");
  };
  const rational = value => {
    const [whole, fraction = ""] = value.split(".");
    return { numerator: BigInt(whole + fraction), denominator: 10n ** BigInt(fraction.length) };
  };
  const ceilDivide = (numerator, denominator) => (numerator + denominator - 1n) / denominator;
  const bitcoin = amount => {
    const fraction = (amount % unit).toString().padStart(8, "0").replace(/0+$/, "");
    return (amount / unit).toString() + (fraction ? "." + fraction : "");
  };

  let marketRequest;
  function fetchMarket() {
    if (!marketRequest) {
      marketRequest = fetch("/api/market", {
        method: "GET", credentials: "same-origin", redirect: "error", cache: "no-store",
        signal: AbortSignal.timeout(20000),
        headers: { Accept: "application/json" }
      }).then(response => {
        if (!response.ok) throw new Error("Market unavailable");
        return response.json();
      });
    }
    return marketRequest;
  }
  /** The largest card count the pricing core accepts; keep in step with pricing._quantity. */
  const MAX_QUANTITY = 100;
  /**
   * Every tag / hand-delivery / wallet combination, in the order pricing.py's
   * /api/market builds them: [key, withTag, handDelivered, hasWallet].
   */
  const VARIANTS = [
    ["no_tag", false, false, false], ["with_tag", true, false, false],
    ["no_tag_in_person", false, true, false], ["with_tag_in_person", true, true, false],
    ["no_tag_wallet", false, false, true], ["with_tag_wallet", true, false, true],
    ["no_tag_in_person_wallet", false, true, true], ["with_tag_in_person_wallet", true, true, true]
  ];
  function validSnapshot(market) {
    return market && ["fresh", "stale"].includes(market.status) &&
      typeof market.fetched_at === "string" &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(market.fetched_at) &&
      Number.isFinite(Date.parse(market.fetched_at)) &&
      market.source?.prices === "https://portal.swapwallet.app/api/v1/market/prices" &&
      market.source?.fees === "https://mempool.space/api/v1/fees/recommended";
  }
  // Decimal rates have power-of-ten denominators: retain every fractional digit.
  function rawValue(sats, price) {
    const rate = rational(price);
    const denominator = rate.denominator * unit;
    const numerator = sats * rate.numerator;
    const fraction = (numerator % denominator).toString()
      .padStart(denominator.toString().length - 1, "0").replace(/0+$/, "");
    return (numerator / denominator).toString() + (fraction ? "." + fraction : "");
  }

(() => {
  if (!document.getElementById("satoshi-converter")) return;
  const btc = document.getElementById("btc-amount");
  const sats = document.getElementById("satoshi-amount");
  const status = document.getElementById("converter-status");
  const grossPanel = document.getElementById("gross-valuation");
  const grossStatus = document.getElementById("gross-status");
  const grossResult = document.getElementById("gross-result");
  const grossToman = document.getElementById("gross-toman");
  let converted = null;
  let rawSnapshot = null;

  function updateGross() {
    grossResult.hidden = true;
    grossToman.textContent = "";
    if (!rawSnapshot || converted === null) return;
    grossToman.textContent = decimal(rawValue(converted, rawSnapshot.raw_rates.btc_toman));
    grossResult.hidden = false;
  }

  function convert(source, destination, fromBitcoin) {
    converted = null;
    updateGross();
    source.removeAttribute("aria-invalid");
    destination.removeAttribute("aria-invalid");
    if (source.value === "") {
      destination.value = "";
      status.textContent = "برای تبدیل، یکی از دو مقدار را با ارقام انگلیسی وارد کنید. هیچ مقداری ارسال نمی‌شود.";
      status.dataset.state = "idle";
      return;
    }
    const pattern = fromBitcoin ? /^(?:0|[1-9][0-9]{0,7})(?:\.[0-9]{1,8})?$/ : /^(?:0|[1-9][0-9]{0,15})$/;
    if (!pattern.test(source.value)) {
      destination.value = "";
      source.setAttribute("aria-invalid", "true");
      status.textContent = "مقدار معتبر نیست؛ فقط ارقام انگلیسی، بدون فاصله یا جداکننده. بیت‌کوین حداکثر هشت رقم اعشار و ساتوشی عدد صحیح دارد.";
      status.dataset.state = "error";
      return;
    }
    const parts = source.value.split(".");
    const amount = fromBitcoin ? BigInt(parts[0]) * unit + BigInt((parts[1] || "").padEnd(8, "0")) : BigInt(source.value);
    if (amount > maximum) {
      destination.value = "";
      source.setAttribute("aria-invalid", "true");
      status.textContent = "مقدار از سقف ۲۱ میلیون بیت‌کوین بیشتر است.";
      status.dataset.state = "error";
      return;
    }
    destination.value = fromBitcoin ? amount.toString() : bitcoin(amount);
    converted = amount;
    updateGross();
    status.textContent = "تبدیل دقیق انجام شد؛ بدون گرد کردن و بدون ارسال اطلاعات.";
    status.dataset.state = "success";
  }

  btc.addEventListener("input", () => convert(btc, sats, true));
  sats.addEventListener("input", () => convert(sats, btc, false));

  async function loadRawRate() {
    grossPanel.setAttribute("aria-busy", "true");
    grossStatus.dataset.state = "loading";
    grossStatus.textContent = "ارزش خام تومانی نیاز به نرخ آنلاین دارد؛ تبدیل بیت‌کوین و ساتوشی آفلاین می‌ماند.";
    try {
      const market = await fetchMarket();
      if (!validSnapshot(market) || !positiveDecimal(market.raw_rates?.btc_toman)) {
        throw new Error("Unexpected raw price");
      }
      rawSnapshot = market;
      document.getElementById("gross-raw-price").textContent = decimal(market.raw_rates.btc_toman);
      document.getElementById("gross-fetched-at").textContent = market.fetched_at;
      document.getElementById("gross-stale").hidden = market.status !== "stale";
      grossStatus.dataset.state = market.status === "stale" ? "stale" : "success";
      grossStatus.textContent = market.status === "stale"
        ? "ارزش خام با نرخ قدیمی ذخیره‌شده؛ این نرخ آنلاینِ تازه نیست."
        : "نرخ آنلاین خام دریافت شد؛ زمان دریافت را ببینید. این ارزش، جمع پرداختی پاکت نیست.";
      updateGross();
    } catch {
      rawSnapshot = null;
      updateGross();
      grossStatus.dataset.state = "error";
      grossStatus.textContent = "نرخ آنلاین در دسترس نیست؛ ارزش تومانی نمایش داده نمی‌شود. تبدیل بیت‌کوین و ساتوشی همچنان آفلاین کار می‌کند.";
    } finally {
      grossPanel.setAttribute("aria-busy", "false");
    }
  }
  loadRawRate();
})();

(() => {
  const panel = document.getElementById("market-panel");
  if (!panel) return;
  const status = document.getElementById("market-status");
  const data = document.getElementById("market-data");
  const stale = document.getElementById("market-stale");
  const rows = document.getElementById("quote-rows");
  const integer = value => Number.isSafeInteger(value) && value >= 0;
  const form = document.getElementById("quote-form");
  const amount = document.getElementById("quote-amount");
  const mode = document.getElementById("quote-mode");
  const calculate = document.getElementById("quote-calculate");
  const quoteStatus = document.getElementById("quote-status");
  const result = document.getElementById("quote-result");
  let snapshot = null;
  let catalog = null;
  let marketSnapshot = null;
  const speed = document.getElementById("quote-speed");
  const tag = document.getElementById("quote-tag");
  const inPerson = document.getElementById("quote-in-person");
  const quantityInput = document.getElementById("quote-quantity");
  const hasWallet = document.getElementById("quote-has-wallet");
  /**
   * The catalog key for the current three-way choice. Hand delivery drops the
   * postal envelope and postage; a buyer who already has a wallet drops the
   * print/seal/label group AND the postal group, because no card is made or
   * mailed. The suffixes are ordered so every one of the eight combinations has
   * its own key, and the server builds exactly the same set.
   */
  const variantName = (withTag, hand, wallet) =>
    (withTag ? "with_tag" : "no_tag") + (hand ? "_in_person" : "") + (wallet ? "_wallet" : "");

  let quantity = 1;

  function quote(principal, cards = quantity) {
    const count = BigInt(cards);
    const network = BigInt(snapshot.costs.network_sats);
    const materials = BigInt(snapshot.costs.materials_sats);
    const envelope = BigInt(snapshot.costs.envelope_sats ?? 0);
    const post = BigInt(snapshot.costs.post_sats);
    const tagCost = BigInt(snapshot.costs.tag_sats ?? 0);
    // The 3.5% acquisition markup already lives in the satoshi price, so the
    // principal is charged once and there is no separate fixed acquisition fee.
    // Three cost groups: the buyer's own purchase cost (inside the rate), the
    // PRINT group (materials + tag) and the POSTAL group (envelope + postage).
    // The card block is spent per paper card; the postal block is spent once per
    // order, so five cards cost less than five separate orders.
    const card = principal + network + materials + tagCost;
    const shared = envelope + post;
    const printMaterials = materials + tagCost;
    const subtotal = card * count + shared;
    const operator = ceilDivide(subtotal * 5n, 100n);
    const total = subtotal + operator;
    const rate = rational(snapshot.rates.satoshi_toman);
    const toman = ceilDivide(total * rate.numerator, rate.denominator);
    // The operator's income in toman: the same 5% fee converted once, never 5% of total-toman.
    const operatorToman = ceilDivide(operator * rate.numerator, rate.denominator);
    // The per-card share of the postal block, rounded UP so the figure never
    // under-states what the buyer pays. Shown for comparison, never charged again.
    const sharedShare = ceilDivide(shared, count);
    return { principal, network, materials, envelope, post,
      "tag-cost-result": tagCost, "print-materials": printMaterials,
      "post-total": envelope + post, "card-sats": card,
      "shared-share": sharedShare, operator, "operator-toman": operatorToman,
      "total-sats": total, "total-toman": toman, "total-rial": toman * 10n };
  }

  /** Read the card count from the input; an invalid value falls back to 1 and is reported. */
  function readQuantity() {
    const raw = (quantityInput?.value ?? "1").trim();
    if (!/^[1-9][0-9]*$/.test(raw)) return null;
    const value = Number(raw);
    return Number.isSafeInteger(value) && value >= 1 && value <= MAX_QUANTITY ? value : null;
  }

  form.addEventListener("submit", event => {
    event.preventDefault();
    clearResult();
    amount.removeAttribute("aria-invalid");
    if (!snapshot) return;
    const cards = readQuantity();
    if (cards === null) {
      reject("تعداد کارت باید عدد صحیح از یک تا صد باشد.");
      return;
    }
    quantity = cards;
    if (!["principal_sats", "budget_toman"].includes(mode.value) ||
        amount.value.length > 32 || !/^[1-9][0-9]*$/.test(amount.value)) {
      reject("مقدار معتبر نیست؛ فقط عدد صحیح مثبت با ارقام انگلیسی، بدون فاصله، جداکننده یا صفر ابتدایی و حداکثر سی‌ودو رقم وارد کنید.");
      return;
    }
    let budget = null;
    let principal = BigInt(amount.value);
    if (mode.value === "principal_sats" && (principal < 501n || principal > maximum)) {
      reject("اصل مبلغ باید از پانصد و یک ساتوشی تا سقف بیست‌ویک میلیون بیت‌کوین باشد.");
      return;
    }
    if (mode.value === "budget_toman") {
      budget = principal;
      if (quote(501n, cards)["total-toman"] > budget) {
        reject("بودجه برای حداقل اصل مبلغ و همهٔ هزینه‌ها کافی نیست؛ بودجه را افزایش دهید.");
        return;
      }
      // Upper-bound search also handles flat price steps and the supply cap.
      let low = 501n;
      let high = maximum;
      while (low < high) {
        const middle = (low + high + 1n) / 2n;
        if (quote(middle, cards)["total-toman"] <= budget) low = middle;
        else high = middle - 1n;
      }
      principal = low;
    }
    const values = quote(principal, cards);
    for (const [name, value] of Object.entries(values)) {
      document.getElementById("quote-" + name).textContent = grouped(value);
    }
    document.getElementById("quote-btc").textContent = bitcoin(values.principal);
    document.getElementById("quote-result-quantity").textContent = cards === 1
      ? "این برآورد برای یک کارت است."
      : "این برآورد برای " + persianDigits(cards) + " کارت است. گروه پست (پاکت و پست) فقط یک‌بار برای کل سفارش حساب شده است.";
    document.getElementById("quote-budget-details").hidden = budget === null;
    document.getElementById("quote-budget").textContent = budget === null ? "" : grouped(budget);
    document.getElementById("quote-remainder").textContent = budget === null ? "" : grouped(budget - values["total-toman"]);
    result.hidden = false;
    const warning = snapshot.status === "stale"
      ? "برآورد با نرخ قدیمی ذخیره‌شده؛ پیش از پرداخت نرخ تازه را بررسی کنید."
      : "برآورد با دادهٔ دریافت‌شده؛ نرخ و پرداخت نهایی تضمین نمی‌شوند.";
    document.getElementById("quote-result-warning").textContent = warning;
    document.getElementById("quote-result-fetched-at").textContent = snapshot.fetched_at;
    quoteStatus.dataset.state = snapshot.status === "stale" ? "stale" : "success";
    quoteStatus.textContent = warning + " ورودی ارسال نشد.";
  });

  function clearResult() {
    result.hidden = true;
    for (const name of ["principal", "btc", "network", "materials", "envelope", "post", "tag-cost-result", "print-materials", "post-total", "operator", "operator-toman", "total-sats", "total-toman",
      "total-rial", "budget", "remainder", "result-warning", "result-fetched-at",
      "card-sats", "shared-share", "result-quantity"]) {
      document.getElementById("quote-" + name).textContent = "";
    }
    document.getElementById("quote-budget-details").hidden = true;
  }
  function reject(message) {
    amount.setAttribute("aria-invalid", "true");
    quoteStatus.textContent = message;
    quoteStatus.dataset.state = "error";
  }
  const invalidate = () => {
    clearResult();
    amount.removeAttribute("aria-invalid");
    if (!snapshot) return;
    quoteStatus.textContent = snapshot.status === "stale"
      ? "نرخ قدیمی ذخیره‌شده است؛ محاسبه فقط برآورد قدیمی می‌دهد."
      : "برای مقدار و واحد انتخاب‌شده، محاسبه را بزنید.";
    quoteStatus.dataset.state = snapshot.status === "stale" ? "stale" : "ready";
  };
  amount.addEventListener("input", invalidate);
  mode.addEventListener("change", invalidate);

  function selectQuote() {
    clearResult();
    const selected = catalog?.[speed.value]?.[variantName(tag.checked, inPerson.checked, hasWallet.checked)];
    if (!selected) {
      snapshot = null;
      calculate.disabled = true;
      data.hidden = true;
      rows.replaceChildren();
      document.getElementById("quote-tag-cost").textContent = "";
      quoteStatus.dataset.state = "error";
      quoteStatus.textContent = "نرخ این انتخاب در دسترس نیست؛ انتخاب دیگری را امتحان کنید.";
      return;
    }
    snapshot = { ...marketSnapshot, ...selected };
    calculate.disabled = false;
    data.hidden = false;
    document.getElementById("network-fee-rate").textContent = decimal(snapshot.assumptions.network_fee_rate);
    document.getElementById("quote-tag-cost").textContent = grouped(snapshot.costs.tag_sats ?? 0);
    rows.replaceChildren(...snapshot.rows.map(quoteRow));
    invalidate();
  }
  speed.addEventListener("change", selectQuote);
  tag.addEventListener("change", selectQuote);
  inPerson.addEventListener("change", selectQuote);
  hasWallet.addEventListener("change", () => {
    // A wallet-only order prints no card, so there is nothing to label: the tag
    // cost is zero and the checkbox is disabled rather than left misleading.
    if (hasWallet.checked) tag.checked = false;
    tag.disabled = hasWallet.checked || !catalog?.economy?.with_tag;
    selectQuote();
  });

  function validMarket(market) {
    if (!validSnapshot(market) ||
        !market.rates || ![market.rates.btc_toman, market.rates.usdt_toman, market.rates.satoshi_toman].every(positiveDecimal) ||
        market.assumptions?.exchange_fee_percent !== "3.5" ||
        market.assumptions?.operator_fee_percent !== "5" ||
        market.assumptions?.materials_usd !== "0.05" || market.assumptions?.envelope_usd !== "0.06" || market.assumptions?.post_usd !== "0.75" ||
        market.assumptions?.transaction_vbytes !== 141 ||
        typeof market.assumptions?.has_wallet !== "boolean" ||
        !positiveDecimal(market.assumptions?.network_fee_rate) ||
        !integer(market.costs?.network_sats) || !integer(market.costs?.materials_sats) ||
        !integer(market.costs?.envelope_sats) ||
        !integer(market.costs?.post_sats) ||
        !integer(market.costs?.tag_sats ?? 0) ||
        !integer(market.costs?.print_materials_sats) || !integer(market.costs?.post_total_sats) ||
        market.costs.print_materials_sats !== market.costs.materials_sats + (market.costs.tag_sats ?? 0) ||
        market.costs.post_total_sats !== market.costs.envelope_sats + market.costs.post_sats ||
        !Number.isInteger(market.quantity) || market.quantity < 1 || market.quantity > MAX_QUANTITY ||
        !integer(market.card_sats) || !integer(market.shared_sats) ||
        market.shared_sats !== market.costs.envelope_sats + market.costs.post_sats ||
        !Array.isArray(market.rows) || market.rows.length < 1 || market.rows.length > 31) return false;
    return market.rows.every((row, index) => {
      if (!row || ![row.principal_sats, row.network_sats,
          row.materials_sats, row.envelope_sats, row.post_sats, row.tag_sats ?? 0, row.operator_sats,
          row.print_materials_sats, row.post_total_sats,
          row.operator_toman, row.total_sats, row.total_toman, row.total_rial, row.remainder_toman].every(integer) ||
          row.principal_sats < 501 || row.principal_sats > 2100000000000000 || row.total_toman === 0 ||
          typeof row.btc !== "string" || !/^(?:0|[1-9][0-9]{0,7})\.[0-9]{8}$/.test(row.btc) ||
          row.network_sats !== market.costs.network_sats || row.materials_sats !== market.costs.materials_sats ||
          row.envelope_sats !== market.costs.envelope_sats ||
          row.post_sats !== market.costs.post_sats ||
          (row.tag_sats ?? 0) !== (market.costs.tag_sats ?? 0) ||
          row.print_materials_sats !== market.costs.print_materials_sats ||
          row.post_total_sats !== market.costs.post_total_sats) return false;
      const [whole, fraction] = row.btc.split(".");
      // quantity and the shared block are per ORDER (top level); each row repeats them.
      const cards = BigInt(market.quantity);
      const cardSats = BigInt(row.principal_sats) + BigInt(row.network_sats) +
        BigInt(row.materials_sats) + BigInt(row.tag_sats ?? 0);
      const sharedSats = BigInt(row.envelope_sats) + BigInt(row.post_sats);
      if (BigInt(row.card_sats) !== cardSats || BigInt(row.shared_sats) !== sharedSats ||
          BigInt(row.shared_sats) !== BigInt(market.shared_sats) ||
          BigInt(row.shared_share_sats) !== ceilDivide(sharedSats, cards) ||
          BigInt(row.quantity) !== cards) return false;
      if (BigInt(whole) * 100000000n + BigInt(fraction) !== BigInt(row.principal_sats) ||
          cardSats * cards + sharedSats + BigInt(row.operator_sats) !== BigInt(row.total_sats) ||
          BigInt(row.total_toman) * 10n !== BigInt(row.total_rial)) return false;
      if (index === 0) return row.principal_sats === 501 && row.budget_toman === null && row.remainder_toman === 0;
      return integer(row.budget_toman) && row.budget_toman >= 100000 && row.budget_toman <= 3000000 &&
        BigInt(row.budget_toman) % 100000n === 0n && row.total_toman <= row.budget_toman &&
        BigInt(row.remainder_toman) === BigInt(row.budget_toman) - BigInt(row.total_toman) &&
        (index === 1 || row.budget_toman > market.rows[index - 1].budget_toman);
    });
  }

  function validChoice(market, choice, withTag, hand, wallet) {
    if (!choice || choice.assumptions?.tag_usd !== "0.12" ||
        choice.assumptions?.include_tag !== withTag ||
        choice.assumptions?.in_person !== hand ||
        choice.assumptions?.has_wallet !== wallet ||
        !integer(choice.costs?.tag_sats) ||
        !validMarket({ ...market, ...choice }) ||
        !["btc_toman", "usdt_toman", "satoshi_toman"].every(key => choice.rates[key] === market.rates[key]) ||
        !/^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,18})?$/.test(choice.assumptions.network_fee_rate)) return false;
    const fee = rational(choice.assumptions.network_fee_rate);
    if (fee.numerator > 10000n * fee.denominator) return false;
    const sat = rational(choice.rates.satoshi_toman);
    const usdt = rational(choice.rates.usdt_toman);
    const dollarCost = cents => ceilDivide(cents * usdt.numerator * sat.denominator,
      100n * usdt.denominator * sat.numerator);
    const network = ceilDivide(fee.numerator * 141n, fee.denominator);
    // Print, seal and the optional label are spent on the card. Hand delivery
    // drops only the postal charges; a buyer who already has a wallet gets no
    // card and no envelope, so both groups are zero for them.
    const mailed = !(hand || wallet);
    const materials = wallet ? 0n : dollarCost(5n);
    const envelope = mailed ? dollarCost(6n) : 0n;
    const post = mailed ? dollarCost(75n) : 0n;
    const tagCost = withTag && !wallet ? dollarCost(12n) : 0n;
    if (BigInt(choice.costs.network_sats) !== network || BigInt(choice.costs.materials_sats) !== materials ||
        BigInt(choice.costs.envelope_sats) !== envelope ||
        BigInt(choice.costs.post_sats) !== post ||
        BigInt(choice.costs.tag_sats) !== tagCost ||
        BigInt(choice.costs.print_materials_sats) !== materials + tagCost ||
        BigInt(choice.costs.post_total_sats) !== envelope + post) return false;
    const cost = (principal, cards) => {
      const subtotal = (principal + network + materials + tagCost) * cards + envelope + post;
      return ceilDivide(ceilDivide(subtotal * 105n, 100n) * sat.numerator, sat.denominator);
    };
    return choice.rows.every(row => {
      if (!integer(row.tag_sats)) return false;
      const principal = BigInt(row.principal_sats);
      const cards = BigInt(choice.quantity);
      const subtotal = (principal + network + materials + tagCost) * cards + envelope + post;
      return BigInt(row.operator_sats) === ceilDivide(subtotal * 5n, 100n) &&
        BigInt(row.operator_toman) === ceilDivide(BigInt(row.operator_sats) * sat.numerator, sat.denominator) &&
        BigInt(row.total_toman) === cost(principal, cards) &&
        (row.budget_toman === null || principal === maximum || cost(principal + 1n, cards) > BigInt(row.budget_toman));
    });
  }

  function element(tag, text, className) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  }

  function quoteRow(row, index) {
    const tr = element("tr");
    const principal = element("th");
    principal.setAttribute("scope", "row");
    principal.append(element("span", grouped(row.principal_sats), "numeric-block"));
    if (index === 0) principal.append(element("small", "حداقل بستهٔ پیشنهادی", "quote-note"));
    const btc = element("td", row.btc, "numeric-block");
    btc.dir = "ltr";
    const total = element("td");
    total.append(element("strong", grouped(row.total_toman), "numeric-block"));
    const details = element("details", undefined, "quote-details");
    const breakdown = element("dl");
    for (const [label, value] of [
      ["اصل مبلغ هر کارت؛ ساتوشی", row.principal_sats],
      ["شبکه (تحویل) هر کارت؛ ساتوشی", row.network_sats],
      ["مواد چاپ و مهر هر کارت؛ ساتوشی", row.materials_sats],
      ["برچسب NFC هر کارت؛ ساتوشی", row.tag_sats ?? 0],
      ["گروه چاپ، مهر و برچسب هر کارت؛ ساتوشی", row.print_materials_sats],
      ["جمع هر کارت؛ ساتوشی", row.card_sats],
      ["پاکت پستی، یک‌بار در سفارش؛ ساتوشی", row.envelope_sats],
      ["پست، یک‌بار در سفارش؛ ساتوشی", row.post_sats],
      ["گروه پست، یک‌بار در سفارش؛ ساتوشی", row.post_total_sats],
      ["سهم هر کارت از گروه پست؛ ساتوشی", row.shared_share_sats],
      ["گرداننده؛ ساتوشی", row.operator_sats],
      ["درآمد گرداننده؛ تومان", row.operator_toman],
      ["جمع؛ ساتوشی", row.total_sats], ["معادل ریال", row.total_rial],
      ...(row.budget_toman === null ? [] : [["بودجه؛ تومان", row.budget_toman], ["باقی‌مانده؛ تومان", row.remainder_toman]])
    ]) {
      const group = element("div");
      const amount = element("dd", grouped(value), "numeric-block");
      amount.dir = "ltr";
      group.append(element("dt", label), amount);
      breakdown.append(group);
    }
    details.append(element("summary", "ریز هزینه و معادل ریال"), breakdown);
    total.append(details);
    tr.append(principal, btc, total);
    return tr;
  }

  async function loadMarket() {
    panel.setAttribute("aria-busy", "true");
    calculate.disabled = true;
    quoteStatus.dataset.state = "loading";
    quoteStatus.textContent = "محاسبه پس از دریافت نرخ از سرور همین سایت آماده می‌شود…";
    document.getElementById("market-loading").hidden = false;
    status.textContent = "در حال دریافت قیمت و کارمزد شبکه؛ لطفاً صبر کنید…";
    status.dataset.state = "loading";
    try {
      const market = await fetchMarket();
      if (!validMarket(market)) throw new Error("Unexpected market data");
      marketSnapshot = market;
      catalog = {};
      for (const name of ["economy", "medium", "fast"]) {
        const choices = market.quote_options?.[name];
        // All eight combinations must be present and self-consistent; the page
        // never invents a variant the server did not price.
        if (choices && VARIANTS.every(([variant, withTag, hand, wallet]) =>
          validChoice(market, choices[variant], withTag, hand, wallet))) catalog[name] = choices;
        document.getElementById("quote-speed-" + name).disabled = !catalog[name];
      }
      // Older snapshots remain usable, but cannot invent tag or priority costs.
      if (market.quote_options === undefined) catalog.economy = { no_tag: market };
      if (!catalog.economy) throw new Error("Economy options unavailable");
      document.getElementById("quote-speed-economy").disabled = false;
      speed.value = "economy";
      tag.checked = false;
      inPerson.checked = false;
      hasWallet.checked = false;
      speed.disabled = false;
      tag.disabled = !catalog.economy.with_tag;
      inPerson.disabled = !catalog.economy.no_tag_in_person;
      hasWallet.disabled = !catalog.economy.no_tag_wallet;
      if (quantityInput) quantityInput.disabled = false;
      document.getElementById("quote-options-status").textContent =
        ["medium", "fast"].some(name => !catalog[name])
          ? "بعضی گزینه‌ها نرخ معتبر ندارند و غیرفعال‌اند؛ نرخ جایگزین فرض نشده است."
          : "هر انتخاب روی جدول و محاسبه‌گر اثر دارد؛ زمان تأیید تضمین نمی‌شود.";
      selectQuote();
      quoteStatus.dataset.state = market.status === "stale" ? "stale" : "ready";
      quoteStatus.textContent = market.status === "stale"
        ? "فقط نرخ قدیمی ذخیره‌شده آماده است؛ محاسبه برآورد قدیمی می‌دهد."
        : "داده آماده است؛ مقدار را وارد و محاسبه را انتخاب کنید.";
      document.getElementById("market-fetched-at").textContent = market.fetched_at;
      document.getElementById("btc-price").textContent = decimal(market.rates.btc_toman);
      document.getElementById("usdt-price").textContent = decimal(market.rates.usdt_toman);
      document.getElementById("sat-price").textContent = decimal(market.rates.satoshi_toman);

      stale.hidden = market.status !== "stale";
      data.hidden = false;
      status.textContent = market.status === "stale" ? "نرخ قدیمی ذخیره‌شده نمایش داده می‌شود؛ پیش از پرداخت قیمت تازه را بررسی کنید." : "برآورد با آخرین دادهٔ دریافت‌شده آماده است؛ نرخ نهایی و زمان تأیید تضمین نمی‌شود.";
      status.dataset.state = market.status === "stale" ? "stale" : "success";
    } catch {
      snapshot = null;
      catalog = null;
      speed.disabled = true;
      tag.disabled = true;
      calculate.disabled = true;
      clearResult();
      quoteStatus.dataset.state = "error";
      quoteStatus.textContent = "نرخ در دسترس نیست؛ محاسبهٔ هزینه ممکن نیست. هیچ نرخ صفر یا جایگزین فرض نشده است.";
      rows.replaceChildren();
      data.hidden = true;
      stale.hidden = true;
      status.textContent = "قیمت و برآورد فعلاً در دسترس نیست. هیچ نرخ صفر یا جایگزینی فرض نشده است؛ بعداً صفحه را بازخوانی کنید.";
      status.dataset.state = "error";
    } finally {
      document.getElementById("market-loading").hidden = true;
      panel.setAttribute("aria-busy", "false");
    }
  }

  loadMarket();
})();
})();
