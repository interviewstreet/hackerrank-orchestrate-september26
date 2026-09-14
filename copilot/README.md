# 🛡️ Personal Financial AI Co-Pilot for India 🇮🇳 ("Buy or Wait?")

> **An intelligent, consumer-centric financial decision co-pilot tailored specifically for Indian consumers navigating UPI, credit cards, and No-Cost EMIs in Indian Rupees (₹).**

---

## 🌟 Overview (Indian Financial Context)

In modern digital India, frictionless payments—1-click UPI checkouts, credit card tap-to-pay, PayLater apps (LazyPay, Simpl), and ubiquitous 3-to-12 month **No-Cost EMI schemes** (Amazon, Flipkart, Bajaj Finserv)—disconnect the immediate feeling of spending from available bank cash. 

Consumers frequently look at their bank account balance, assume they can afford a ₹79,900 iPhone or an expensive weekend trip, forgetting that:
- **Rent & Society Maintenance** are due on the 5th.
- **Car / Bike EMI & Mutual Fund SIPs** auto-debit on the 7th–10th.
- **Credit card bills (HDFC, ICICI, SBI)** are due on the 12th–15th.
- Auto-debit bounces (NACH/e-mandates) incur penalty charges of ₹400–₹500 + GST per occurrence.

**Buy or Wait? India Co-Pilot** acts as your 24/7 financial co-pilot before you tap "Buy Now" or scan a QR code:
1. **Simulates 90-day forward bank cash flow** day-by-day in Indian Rupees (`₹`).
2. **Enforces a strict Emergency Cushion** (Fixed Deposit / Liquid reserve floor).
3. **Accounts for fixed obligations & recurring auto-debits** (Rent, Car EMI, SIPs, Credit Card dues, BESCOM electricity, Cook/Maid).
4. **Delivers a mathematically grounded verdict**:
   - 🟢 **Affordable Now (UPI / Pay in Full)**: Safe to pay today without risking your cushion.
   - 🟡 **Affordable with No-Cost EMI / Plan**: Safe via structured 3/6/9/12-month EMIs or budget trade-offs.
   - 🟠 **Affordable Later (Wait for Salary)**: Safe to purchase on an exact future date when your monthly salary credits.
   - 🔴 **Not Recommended**: Danger of dipping into your emergency fund or triggering ECS bounce fees.
5. **Recommends actionable budget trade-offs**: Identifies specific controllable spending (Swiggy, Zomato, Blinkit, OTT packs, weekend dining) to pause or reduce to afford your purchase today safely.

---

## 🚀 Quickstart

### Launch the Web Application
Zero external dependencies required! Runs with standard Python 3.11+:

```bash
# From repository root
python app.py
```

Options:
- `--port <PORT>`: Change listening port (default: `8000`).
- `--host <HOST>`: Change host address (default: `127.0.0.1`).
- `--no-browser`: Disable automatic browser launch.

Open your browser at:
👉 **`http://localhost:8000`**

---

## 🇮🇳 Pre-Configured Indian Consumer Personas

The application comes preloaded with authentic Indian financial personas:
1. **Aarav Sharma — Bangalore Techie (₹85,000 Balance, ₹45,000 Cushion)**
   - Monthly salary: ₹1,40,000.
   - Fixed debits: HSR Layout 2BHK Rent (₹35,000), Car EMI (₹14,500), Nifty 50 SIP (₹15,000), HDFC Card Due (₹22,000), BESCOM & WiFi (₹3,500).
   - Flexible cuts: Swiggy/Zomato (₹6,000), Weekend outings (₹4,500), OTT packs (₹1,199).
2. **Priya Patel — Mumbai Marketer (₹48,000 Balance, ₹25,000 Cushion)**
   - Monthly salary: ₹80,000.
   - Fixed debits: Andheri West Rent (₹24,000), ICICI Card Due (₹12,000), Cult.fit Gym (₹2,500).
   - Flexible cuts: Myntra/Zara shopping (₹5,500).
3. **Dataset Indian Users**: 60+ real dataset profiles in INR (`user_07`, `user_33`, `user_34`, `user_35`, etc.).
4. **Custom Profile**: Any Indian user can set their own bank balance, emergency reserve, salary dates, and obligations.

---

## 🖥️ Key Features in the Indian Co-Pilot

### 1. Executive Financial Health KPIs (₹ INR)
- **Bank Account Balance**: Liquid savings account balance.
- **Emergency Safety Cushion**: Protected FD / liquid cushion (never breached).
- **Safe UPI / Headroom Today**: Safe immediate spending capacity.
- **30-Day Obligations & EMIs**: Total scheduled auto-debits before next salary.

### 2. "Can I Afford This?" Instant Simulator
- Contemplate any purchase: *Apple iPhone 16 (128GB)*, *Royal Enfield Hunter 350*, *Sony Bravia 4K TV*, *Goa Diwali Vacation*, *Gold Jewellery*.
- Select No-Cost EMI options (3, 6, 9, 12 months) or full UPI/Debit payment.
- View immediate verdict badge, safe today amount, and exact trade-off recommendations.

### 3. Interactive Conversational Assistant ("Chat with Co-Pilot")
Supports natural Indian English with Lakhs, Rupee symbols, and EMI terms:
- *"Can I buy iPhone 16 for ₹79,900 on 6-month No-Cost EMI?"*
- *"Can I afford 1.5 lakh for Royal Enfield bike?"*
- *"How much safe UPI budget do I have today?"*
- *"What EMIs and credit card bills are due this month?"*
- *"Can I afford a Goa trip for ₹35,000 if I reduce Swiggy orders?"*

### 4. Interactive 90-Day Cash Curve Trajectory Chart (Chart.js)
- **Blue line**: Baseline status-quo bank balance.
- **Orange dashed line**: Balance if paid in full today (visually exposing dips below the red line).
- **Green line**: Balance with the Co-Pilot's recommended EMI or plan.
- **Red dashed line**: Strict Emergency Cushion threshold.

---

## 🧪 Testing

Run all unit and integration tests:
```bash
# Run copilot tests
python -m unittest discover -s copilot/tests

# Run full project pytest suite (27 tests)
pytest tests/ copilot/tests/
```
