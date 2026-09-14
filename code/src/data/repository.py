import csv
from datetime import date
from pathlib import Path
from code.src.models import (
    RequestContext,
    UserFinancialProfile,
    FinancialEvent,
    PaymentOption,
)
from code.src.data.loaders import (
    load_requests,
    load_profiles,
    load_events,
    load_payment_options,
    parse_date,
)


class DataRepository:
    def __init__(self, dataset_dir: Path):
        self.dataset_dir = dataset_dir

        self.requests: dict[str, RequestContext] = {}
        self.profiles: dict[str, UserFinancialProfile] = {}
        self.events_by_user: dict[str, list[FinancialEvent]] = {}
        self.events_by_id: dict[str, FinancialEvent] = {}
        self.options_by_request: dict[str, list[PaymentOption]] = {}
        self.messages_by_user: dict[str, list[dict]] = {}
        self.messages_by_event: dict[str, list[dict]] = {}
        self.images_by_user: dict[str, list[dict]] = {}
        self.images_by_event: dict[str, dict] = {}
        self.images_by_request: dict[str, list[dict]] = {}
        self.exchange_rates: dict[tuple[str, str, date], float] = {}

        self.load_all()

    def load_all(self):
        # 1. Requests
        req_file = self.dataset_dir / "requests.csv"
        if req_file.exists():
            self.requests.update(load_requests(req_file))

        sample_req_file = self.dataset_dir / "sample_requests.csv"
        if sample_req_file.exists():
            # Include sample requests as well for testing & evaluation
            self.requests.update(load_requests(sample_req_file))

        # 2. Profiles
        prof_file = self.dataset_dir / "financial_profiles.csv"
        if prof_file.exists():
            self.profiles = load_profiles(prof_file)

        # 3. Events
        ev_file = self.dataset_dir / "financial_events.csv"
        if ev_file.exists():
            events = load_events(ev_file)
            for ev in events:
                self.events_by_user.setdefault(ev.user_id, []).append(ev)
                self.events_by_id[ev.event_id] = ev

        # 4. Payment options
        opt_file = self.dataset_dir / "request_payment_options.csv"
        if opt_file.exists():
            options = load_payment_options(opt_file)
            for opt in options:
                self.options_by_request.setdefault(opt.request_id, []).append(opt)

        # 5. Messages
        msg_file = self.dataset_dir / "messages.csv"
        if msg_file.exists():
            with open(msg_file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    msg_dict = dict(row)
                    u_id = row["user_id"].strip()
                    ev_id = row.get("related_event_id", "").strip()
                    self.messages_by_user.setdefault(u_id, []).append(msg_dict)
                    if ev_id:
                        self.messages_by_event.setdefault(ev_id, []).append(msg_dict)

        # 6. Images
        img_file = self.dataset_dir / "images.csv"
        if img_file.exists():
            with open(img_file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    img_dict = dict(row)
                    u_id = row["user_id"].strip()
                    r_id = row["request_id"].strip()
                    ev_id = row["related_event_id"].strip()
                    self.images_by_user.setdefault(u_id, []).append(img_dict)
                    self.images_by_request.setdefault(r_id, []).append(img_dict)
                    self.images_by_event[ev_id] = img_dict

        # 7. Exchange rates
        fx_file = self.dataset_dir / "exchange_rates.csv"
        if fx_file.exists():
            with open(fx_file, mode="r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    r_date = parse_date(row["rate_date"])
                    from_c = row["from_currency"].strip()
                    to_c = row["to_currency"].strip()
                    rate_val = float(row["rate"])
                    self.exchange_rates[(from_c, to_c, r_date)] = rate_val

    def get_request(self, request_id: str) -> RequestContext | None:
        return self.requests.get(request_id)

    def get_profile(self, user_id: str) -> UserFinancialProfile | None:
        return self.profiles.get(user_id)

    def get_events(self, user_id: str) -> list[FinancialEvent]:
        return self.events_by_user.get(user_id, [])

    def get_payment_options(self, request_id: str) -> list[PaymentOption]:
        return self.options_by_request.get(request_id, [])

    def get_messages(self, user_id: str, request_id: str | None = None) -> list[dict]:
        user_msgs = self.messages_by_user.get(user_id, [])
        if not request_id:
            return user_msgs
        # Filter messages relevant to request or general to user
        return [m for m in user_msgs if not m.get("request_id") or m.get("request_id") == request_id]

    def get_images(self, user_id: str, request_id: str | None = None) -> list[dict]:
        user_imgs = self.images_by_user.get(user_id, [])
        if not request_id:
            return user_imgs
        return [img for img in user_imgs if not img.get("request_id") or img.get("request_id") == request_id]

    def get_image_for_event(self, event_id: str) -> dict | None:
        return self.images_by_event.get(event_id)

    def lookup_exchange_rate_detailed(
        self, from_curr: str, to_curr: str, rate_date: date
    ) -> tuple[float, date, str | None]:
        if from_curr == to_curr:
            return 1.0, rate_date, None

        # 1. Exact match on (from_curr, to_curr, rate_date)
        key = (from_curr, to_curr, rate_date)
        if key in self.exchange_rates:
            return self.exchange_rates[key], rate_date, None

        # 2. Exact inverse match on rate_date
        inv_key = (to_curr, from_curr, rate_date)
        if inv_key in self.exchange_rates:
            return 1.0 / self.exchange_rates[inv_key], rate_date, None

        # 3. Fallback: nearest available rate date for this currency pair
        matching = [
            (d, r) for (fc, tc, d), r in self.exchange_rates.items()
            if fc == from_curr and tc == to_curr
        ] + [
            (d, 1.0 / r) for (fc, tc, d), r in self.exchange_rates.items()
            if fc == to_curr and tc == from_curr
        ]
        if matching:
            matching.sort(key=lambda item: abs((item[0] - rate_date).days))
            closest_d, rate = matching[0]
            warning = f"Exchange rate for {from_curr}->{to_curr} on {rate_date} not found. Used fallback rate from closest date {closest_d}."
            return rate, closest_d, warning

        # 4. Triangulation via USD or EUR
        for mid in ["USD", "EUR"]:
            r1 = self.get_exchange_rate_direct(from_curr, mid, rate_date)
            r2 = self.get_exchange_rate_direct(mid, to_curr, rate_date)
            if r1 is not None and r2 is not None:
                warning = f"Exchange rate for {from_curr}->{to_curr} on {rate_date} triangulated via {mid}."
                return r1 * r2, rate_date, warning

        # 5. Unavailable: do not invent a rate
        warning = f"Exchange rate for {from_curr}->{to_curr} on {rate_date} is unavailable in exchange_rates.csv."
        return 1.0, rate_date, warning

    def get_exchange_rate(self, from_curr: str, to_curr: str, rate_date: date) -> float:
        rate, _, _ = self.lookup_exchange_rate_detailed(from_curr, to_curr, rate_date)
        return rate

    def get_exchange_rate_direct(self, from_curr: str, to_curr: str, rate_date: date) -> float | None:
        if from_curr == to_curr:
            return 1.0
        if (from_curr, to_curr, rate_date) in self.exchange_rates:
            return self.exchange_rates[(from_curr, to_curr, rate_date)]
        if (to_curr, from_curr, rate_date) in self.exchange_rates:
            return 1.0 / self.exchange_rates[(to_curr, from_curr, rate_date)]
        # nearest date
        matching = [
            (d, r) for (fc, tc, d), r in self.exchange_rates.items()
            if (fc == from_curr and tc == to_curr) or (fc == to_curr and tc == from_curr)
        ]
        if matching:
            matching.sort(key=lambda item: abs((item[0] - rate_date).days))
            closest_d, rate = matching[0]
            if (from_curr, to_curr, closest_d) in self.exchange_rates:
                return rate
            return 1.0 / rate
        return None
