# 🛡️ Personal Financial AI Co-Pilot ("Buy or Wait?")

> **An intelligent, consumer-centric financial decision co-pilot that protects consumers in the modern credit and BNPL economy.**

---

## 🌟 Overview

In the modern digital economy, frictionless credit cards and Buy Now Pay Later (BNPL) schemes make spending impulsive while obscuring future obligations (rent, car insurance, EMIs, utility bills). Consumers often check their current account balance, assume they can afford a purchase, and end up in overdraft fees or debt spirals.

**Buy or Wait? AI Financial Co-Pilot** is an interactive financial assistant designed to solve this exact problem. Before you make any purchase or commitment, the Co-Pilot:
1. **Simulates 90-day forward cash flow** day-by-day.
2. **Enforces a strict Emergency Cushion** (minimum balance floor).
3. **Accounts for fixed obligations & recurring bills** (rent, EMIs, utilities, subscriptions).
4. **Delivers a clear, mathematically grounded verdict**:
   - 🟢 **Affordable Now (Pay in Full)**: Safe today without risking your cushion.
   - 🟡 **Affordable with Plan**: Safe via structured installments or smart budget adjustments.
   - 🟠 **Affordable Later (Wait)**: Safe to purchase on an exact future date (e.g., after confirmed salary).
   - 🔴 **Not Recommended**: Unsafe spending that depletes your emergency reserve.
5. **Recommends actionable trade-offs**: If you urgently need the item today, it tells you exactly what discretionary spending to pause or cut to make it safe.

---

## 🚀 Quickstart

### 1. Launch the Web Application
No external web frameworks or heavy dependencies required! Run with standard Python 3.11+:

```bash
# From repository root
python app.py
```

Options:
- `--port <PORT>`: Change listening port (default: `8000`).
- `--host <HOST>`: Change host address (default: `127.0.0.1`).
- `--no-browser`: Disable automatic browser launch.

The application will be accessible in your browser at:
👉 **`http://localhost:8000`**

---

## 🖥️ User Interface & Key Features

### 1. Executive Financial Health KPIs
- **Available Cash Balance**: Liquid checking/savings funds.
- **Emergency Safety Cushion**: Strict minimum balance floor that is never breached.
- **Safe Headroom Today**: Instant discretionary spending capacity.
- **30-Day Obligations**: Total upcoming fixed debits (rent, debts, utilities).

### 2. "Can I Afford This?" Instant Evaluator
- Enter what you want to buy (e.g., *Sony WH-1000XM5*, *MacBook Pro*, *Weekend Getaway*), price, and category.
- Toggle financing options (Pay in full, 3-month split, 6-month split).
- Receive instant verdict badges, earliest safe dates, and specific trade-off recommendations.

### 3. Interactive Conversational Assistant ("Chat with Co-Pilot")
Converse in plain English with sample queries:
- *"Can I buy a laptop for $950?"*
- *"How much can I safely spend today?"*
- *"What bills are due in the next 30 days?"*
- *"How does my emergency cushion protect me?"*

### 4. Interactive 90-Day Cash Flow Trajectory Chart (Chart.js)
Visual proof of your financial timeline:
- **Blue Line**: Baseline balance trajectory (status quo).
- **Orange Dashed Line**: Balance trajectory if you buy in full today.
- **Green Line**: Balance trajectory with the Co-Pilot's recommendation.
- **Red Dashed Floor**: Emergency Cushion line (strict safety boundary).

### 5. Profile & Cushion Customizer
- Adjust your current balance, emergency cushion reserve, and maximum installment preferences.
- Add upcoming custom income deposits or expense bills in real time.

---

## 🏗️ Architecture & Implementation

```
copilot/
├── backend/
│   ├── __init__.py
│   ├── state.py         # State management & custom profile store
│   ├── engine.py        # Core simulation bridge & financial evaluation
│   ├── assistant.py     # NLP query parser & conversational adviser
│   └── server.py        # High-performance zero-dependency HTTP server
├── static/
│   ├── index.html       # Responsive Tailwind CSS single-page app
│   ├── style.css        # Clean styling & glassmorphism accents
│   └── app.js           # Chart.js rendering, live chat, and API reactivity
├── tests/
│   ├── __init__.py
│   ├── test_copilot.py  # Unit tests for simulation & assistant
│   └── test_server.py   # HTTP API endpoint tests
└── README.md            # Documentation
app.py                   # Root application launcher
```

### REST API Endpoints
- `GET /`: Serves the interactive Web UI.
- `GET /api/users`: List available user profiles.
- `POST /api/user/select`: Switch active profile.
- `GET /api/summary`: Fetch current balance, emergency cushion, and safe headroom.
- `POST /api/profile`: Update account balance and emergency cushion.
- `POST /api/event/add`: Add a scheduled bill or income event.
- `POST /api/evaluate`: Run 90-day simulation for a proposed purchase.
- `POST /api/chat`: Send a conversational query to the AI Assistant.
- `GET /api/chat/history`: Retrieve conversation history.

---

## 🧪 Running Tests

Run all unit and integration tests:
```bash
python -m unittest discover -s copilot/tests
# Or with pytest
pytest copilot/tests/
```
