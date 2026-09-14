// Buy or Wait? AI Financial Co-Pilot (India 🇮🇳) Frontend Application
let activeUserId = "aarav_in";
let currentSummary = null;
let cashChart = null;

// Initialize on page load
document.addEventListener("DOMContentLoaded", () => {
    loadUsers();
    setupEventListeners();
    loadChatHistory();
});

// Setup event listeners
function setupEventListeners() {
    // User select dropdown
    document.getElementById("userSelect").addEventListener("change", (e) => {
        selectUser(e.target.value);
    });

    // Purchase evaluation form
    document.getElementById("evalForm").addEventListener("submit", (e) => {
        e.preventDefault();
        evaluatePurchase();
    });

    // Chat form
    document.getElementById("chatForm").addEventListener("submit", (e) => {
        e.preventDefault();
        sendChatMessage();
    });

    // Profile modal
    document.getElementById("btnEditProfile").addEventListener("click", () => {
        openProfileModal();
    });
    document.getElementById("btnCloseProfileModal").addEventListener("click", () => {
        closeProfileModal();
    });
    document.getElementById("profileForm").addEventListener("submit", (e) => {
        e.preventDefault();
        saveProfile();
    });

    // Add event modal
    document.getElementById("btnAddEvent").addEventListener("click", () => {
        openEventModal();
    });
    document.getElementById("btnCloseEventModal").addEventListener("click", () => {
        closeEventModal();
    });
    document.getElementById("eventForm").addEventListener("submit", (e) => {
        e.preventDefault();
        saveEvent();
    });
}

// Load users from backend
async function loadUsers() {
    try {
        const res = await fetch("/api/users");
        const data = await res.json();
        const select = document.getElementById("userSelect");
        select.innerHTML = "";
        
        data.users.forEach(u => {
            const opt = document.createElement("option");
            opt.value = u.user_id;
            opt.textContent = `${u.display_name || u.user_id} (₹${formatCur(u.balance)} | Cushion: ₹${formatCur(u.min_balance)})`;
            if (u.user_id === data.active_user_id) {
                opt.selected = true;
                activeUserId = u.user_id;
            }
            select.appendChild(opt);
        });

        loadSummary(activeUserId);
    } catch (err) {
        console.error("Failed to load users:", err);
    }
}

// Select active user
async function selectUser(userId) {
    try {
        const res = await fetch("/api/user/select", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ user_id: userId })
        });
        const data = await res.json();
        if (data.success) {
            activeUserId = userId;
            renderSummary(data.summary);
            evaluatePurchase(true);
        }
    } catch (err) {
        console.error("Failed to select user:", err);
    }
}

// Load summary for active user
async function loadSummary(userId) {
    try {
        const res = await fetch(`/api/summary?user_id=${userId}`);
        const data = await res.json();
        renderSummary(data);
        evaluatePurchase(true);
    } catch (err) {
        console.error("Failed to load summary:", err);
    }
}

// Render financial KPI summary
function renderSummary(summary) {
    currentSummary = summary;
    const curSym = "₹";

    document.getElementById("kpiBalance").textContent = `${curSym}${formatCur(summary.current_balance)}`;
    document.getElementById("kpiCushion").textContent = `${curSym}${formatCur(summary.emergency_cushion)}`;
    document.getElementById("kpiHeadroom").textContent = `${curSym}${formatCur(summary.safe_headroom_today)}`;
    document.getElementById("kpiDebits").textContent = `${curSym}${formatCur(summary.upcoming_30d_debits_total)}`;

    // Headroom badge color
    const headroomCard = document.getElementById("cardHeadroom");
    if (summary.safe_headroom_today <= 0) {
        headroomCard.classList.remove("border-emerald-500", "border-blue-500");
        headroomCard.classList.add("border-rose-500");
    } else {
        headroomCard.classList.remove("border-rose-500");
        headroomCard.classList.add("border-emerald-500");
    }

    // Render upcoming commitments table
    renderCommitmentsTable(summary.upcoming_commitments, curSym);
}

// Render obligations table
function renderCommitmentsTable(commitments, curSym) {
    const tbody = document.getElementById("commitmentsTbody");
    tbody.innerHTML = "";

    if (!commitments || commitments.length === 0) {
        tbody.innerHTML = `<tr><td colspan="4" class="py-4 text-center text-slate-400 text-sm">No scheduled debits in the next 30 days.</td></tr>`;
        return;
    }

    commitments.forEach(c => {
        const tr = document.createElement("tr");
        tr.className = "border-b border-slate-100 hover:bg-slate-50 transition-colors";
        tr.innerHTML = `
            <td class="py-2.5 px-3 text-sm font-medium text-slate-700">${c.settlement_date}</td>
            <td class="py-2.5 px-3 text-sm text-slate-800">
                <span class="font-medium">${escapeHtml(c.description)}</span>
                ${c.is_recurring ? '<span class="ml-1 text-xs px-1.5 py-0.5 rounded bg-blue-50 text-blue-600">Auto-Debit</span>' : ''}
            </td>
            <td class="py-2.5 px-3 text-sm text-slate-500 capitalize">${escapeHtml(c.category)}</td>
            <td class="py-2.5 px-3 text-sm font-semibold text-rose-600 text-right">-${curSym}${formatCur(c.amount)}</td>
        `;
        tbody.appendChild(tr);
    });
}

// Evaluate purchase
async function evaluatePurchase(isInitial = false) {
    const itemName = document.getElementById("itemName").value.trim() || (isInitial ? "Apple iPhone 16 (128GB)" : "Sample Item");
    const amount = parseFloat(document.getElementById("itemAmount").value) || (isInitial ? 79900 : 0);
    const category = document.getElementById("itemCategory").value;
    const customInstallments = document.getElementById("installmentOption").value;
    const willingAdjust = document.getElementById("willingAdjust").checked;

    if (amount <= 0 && !isInitial) {
        alert("Please enter a valid purchase amount in Rupees (₹).");
        return;
    }

    const btn = document.getElementById("btnEvaluate");
    if (!isInitial) {
        btn.disabled = true;
        btn.innerHTML = `<svg class="animate-spin -ml-1 mr-2 h-4 w-4 text-white inline" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path></svg> Simulating 90-Day Cash Flow...`;
    }

    try {
        const res = await fetch("/api/evaluate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: activeUserId,
                item_name: itemName,
                amount: amount,
                category: category,
                custom_installment_months: customInstallments ? parseInt(customInstallments) : null,
                willing_to_adjust_spending: willingAdjust,
            })
        });
        const result = await res.json();
        renderEvaluationResult(result, isInitial);
        renderCashChart(result.chart_timeline, result.currency);
    } catch (err) {
        console.error("Evaluation error:", err);
    } finally {
        if (!isInitial) {
            btn.disabled = false;
            btn.innerHTML = `🛡️ Evaluate Affordability`;
        }
    }
}

// Render purchase evaluation result card
function renderEvaluationResult(res, isInitial) {
    const card = document.getElementById("evalResultCard");
    card.classList.remove("hidden");

    const badge = document.getElementById("evalStatusBadge");
    const methodSpan = document.getElementById("evalMethod");
    const safeTodaySpan = document.getElementById("evalSafeToday");
    const earliestDateSpan = document.getElementById("evalEarliestDate");
    const planSpan = document.getElementById("evalPlan");
    const explanationDiv = document.getElementById("evalExplanation");
    const changesList = document.getElementById("evalChangesList");
    const changesContainer = document.getElementById("evalChangesContainer");

    const curSym = "₹";

    // Clear badge classes
    badge.className = "px-3 py-1.5 rounded-full text-xs font-bold uppercase tracking-wider inline-flex items-center gap-1.5";

    if (res.affordability_status === "affordable_now") {
        badge.classList.add("badge-affordable-now");
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-emerald-500"></span> Affordable Now (UPI / Pay in Full)`;
    } else if (res.affordability_status === "affordable_with_plan") {
        badge.classList.add("badge-affordable-with-plan");
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-amber-500"></span> Affordable with No-Cost EMI / Plan`;
    } else if (res.affordability_status === "affordable_later") {
        badge.classList.add("badge-affordable-later");
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-orange-500"></span> Affordable Later (Wait for Salary)`;
    } else {
        badge.classList.add("badge-not-affordable");
        badge.innerHTML = `<span class="w-2 h-2 rounded-full bg-rose-500"></span> Not Recommended (Violates Cushion)`;
    }

    methodSpan.textContent = res.recommended_payment_method;
    safeTodaySpan.textContent = `${curSym}${formatCur(res.amount_safe_to_pay_today)}`;
    earliestDateSpan.textContent = res.earliest_date_for_full_payment || "N/A";
    planSpan.textContent = res.payment_plan_summary !== "none" ? res.payment_plan_summary : "None (Pay in full or wait)";

    explanationDiv.innerHTML = formatMarkdown(res.explanation);

    // Trade-off changes
    if (res.human_spending_changes && res.human_spending_changes.length > 0) {
        changesContainer.classList.remove("hidden");
        changesList.innerHTML = "";
        res.human_spending_changes.forEach(ch => {
            const li = document.createElement("li");
            li.className = "flex items-start gap-2 text-sm text-slate-700";
            li.innerHTML = `<span class="text-amber-500 font-bold">✂️</span> <span>${escapeHtml(ch)}</span>`;
            changesList.appendChild(li);
        });
    } else {
        changesContainer.classList.add("hidden");
    }
}

// Render Chart.js 90-Day Cash Flow Trajectory
function renderCashChart(timeline, currency) {
    if (!timeline || timeline.length === 0) return;

    const curSym = currency === "INR" ? "₹" : `${currency} `;
    const ctx = document.getElementById("cashFlowChart").getContext("2d");

    const labels = timeline.map(p => p.date.substring(5)); // MM-DD
    const baselineData = timeline.map(p => p.baseline);
    const purchaseData = timeline.map(p => p.after_full_purchase);
    const planData = timeline.map(p => p.with_copilot_recommendation);
    const cushionData = timeline.map(p => p.emergency_floor);

    if (cashChart) {
        cashChart.destroy();
    }

    cashChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: labels,
            datasets: [
                {
                    label: "Baseline Bank Balance (No Purchase)",
                    data: baselineData,
                    borderColor: "#3b82f6", // Blue
                    backgroundColor: "rgba(59, 130, 246, 0.05)",
                    borderWidth: 2,
                    tension: 0.2,
                    pointRadius: 1,
                },
                {
                    label: "If Paid in Full Today",
                    data: purchaseData,
                    borderColor: "#f97316", // Orange
                    borderDash: [5, 5],
                    borderWidth: 2,
                    tension: 0.2,
                    pointRadius: 1,
                },
                {
                    label: "With Co-Pilot Recommendation (EMI / Safe Plan)",
                    data: planData,
                    borderColor: "#10b981", // Emerald
                    borderWidth: 2.5,
                    tension: 0.2,
                    pointRadius: 1,
                },
                {
                    label: "Emergency Reserve Floor (Protected Cushion)",
                    data: cushionData,
                    borderColor: "#ef4444", // Red
                    borderDash: [4, 4],
                    borderWidth: 2,
                    pointRadius: 0,
                    fill: false,
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: "index",
                intersect: false,
            },
            plugins: {
                legend: {
                    position: "top",
                    labels: {
                        boxWidth: 12,
                        font: { size: 12 }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            return `${context.dataset.label}: ${curSym}${formatCur(context.parsed.y)}`;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { display: false },
                    ticks: { maxTicksLimit: 12 }
                },
                y: {
                    grid: { color: "#f1f5f9" },
                    ticks: {
                        callback: function(value) {
                            return `${curSym}${Number(value).toLocaleString("en-IN")}`;
                        }
                    }
                }
            }
        }
    });
}

// Send chat message
async function sendChatMessage() {
    const input = document.getElementById("chatInput");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    appendChatMessage("user", text);

    const typingId = appendTypingIndicator();

    try {
        const res = await fetch("/api/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: activeUserId,
                message: text,
            })
        });
        const data = await res.json();
        removeTypingIndicator(typingId);
        appendChatMessage("assistant", data.content);

        // If assistant response evaluated a purchase, update the dashboard chart & simulator
        if (data.type === "purchase_evaluation" && data.evaluation) {
            renderEvaluationResult(data.evaluation, false);
            renderCashChart(data.evaluation.chart_timeline, data.evaluation.currency);
        }
    } catch (err) {
        removeTypingIndicator(typingId);
        appendChatMessage("assistant", "⚠️ Sorry, I encountered an issue analyzing your cash flow. Please try again.");
    }
}

// Append chat message to conversation UI
function appendChatMessage(role, content) {
    const container = document.getElementById("chatMessages");
    const msgDiv = document.createElement("div");
    msgDiv.className = `flex ${role === "user" ? "justify-end" : "justify-start"} mb-3`;

    const bubble = document.createElement("div");
    bubble.className = `max-w-[85%] px-4 py-3 text-sm ${role === "user" ? "chat-bubble-user" : "chat-bubble-assistant shadow-sm"}`;
    bubble.innerHTML = formatMarkdown(content);

    msgDiv.appendChild(bubble);
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

// Quick prompt chip click handler
function sendQuickPrompt(promptText) {
    document.getElementById("chatInput").value = promptText;
    sendChatMessage();
}

function appendTypingIndicator() {
    const id = `typing_${Date.now()}`;
    const container = document.getElementById("chatMessages");
    const div = document.createElement("div");
    div.id = id;
    div.className = "flex justify-start mb-3";
    div.innerHTML = `
        <div class="chat-bubble-assistant px-4 py-2.5 text-xs text-slate-500 flex items-center gap-2">
            <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse delay-75"></span>
            <span class="w-1.5 h-1.5 rounded-full bg-slate-400 animate-pulse delay-150"></span>
            <span>Simulating bank cash flow...</span>
        </div>
    `;
    container.appendChild(div);
    container.scrollTop = container.scrollHeight;
    return id;
}

function removeTypingIndicator(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

// Load chat history
async function loadChatHistory() {
    try {
        const res = await fetch("/api/chat/history");
        const data = await res.json();
        const container = document.getElementById("chatMessages");
        container.innerHTML = "";
        data.history.forEach(m => {
            appendChatMessage(m.role, m.content);
        });
    } catch (err) {
        console.error("Failed to load chat history:", err);
    }
}

// Profile modal handling
function openProfileModal() {
    if (!currentSummary) return;
    document.getElementById("editBalance").value = currentSummary.current_balance;
    document.getElementById("editCushion").value = currentSummary.emergency_cushion;
    document.getElementById("editMaxInstallments").value = currentSummary.max_installment_months || "";
    document.getElementById("profileModal").classList.remove("hidden");
}

function closeProfileModal() {
    document.getElementById("profileModal").classList.add("hidden");
}

async function saveProfile() {
    const bal = parseFloat(document.getElementById("editBalance").value);
    const cushion = parseFloat(document.getElementById("editCushion").value);
    const maxInst = document.getElementById("editMaxInstallments").value;

    try {
        const res = await fetch("/api/profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: activeUserId,
                current_available_balance: bal,
                minimum_balance_to_keep: cushion,
                max_installment_months: maxInst ? parseInt(maxInst) : null,
            })
        });
        const data = await res.json();
        if (data.success) {
            closeProfileModal();
            renderSummary(data.summary);
            evaluatePurchase(true);
            appendChatMessage("assistant", `✅ Updated your Indian financial profile: Bank Balance set to **₹${formatCur(bal)}**, Emergency Cushion set to **₹${formatCur(cushion)}**.`);
        }
    } catch (err) {
        alert("Failed to save profile.");
    }
}

// Event modal handling
function openEventModal() {
    document.getElementById("eventModal").classList.remove("hidden");
}

function closeEventModal() {
    document.getElementById("eventModal").classList.add("hidden");
}

async function saveEvent() {
    const desc = document.getElementById("eventDesc").value.trim();
    const amount = parseFloat(document.getElementById("eventAmount").value);
    const type = document.getElementById("eventType").value;
    const cat = document.getElementById("eventCategory").value;
    const sDate = document.getElementById("eventDate").value;

    if (!desc || amount <= 0 || !sDate) {
        alert("Please fill all event fields.");
        return;
    }

    try {
        const res = await fetch("/api/event/add", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                user_id: activeUserId,
                description: desc,
                amount: amount,
                event_type: type,
                category: cat,
                settlement_date: sDate,
                currency: "INR",
            })
        });
        const data = await res.json();
        if (data.success) {
            closeEventModal();
            renderSummary(data.summary);
            evaluatePurchase(true);
            appendChatMessage("assistant", `🗓️ Added scheduled ${type}: **${desc}** (₹${formatCur(amount)} on ${sDate}).`);
        }
    } catch (err) {
        alert("Failed to add event.");
    }
}

// Indian Number Formatting Utility (en-IN)
function formatCur(val) {
    if (val === undefined || val === null || isNaN(val)) return "0.00";
    return Number(val).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function formatMarkdown(text) {
    if (!text) return "";
    text = text.replace(/([0-9,]+(?:\.[0-9]{2})?)\s*ZAR\b/gi, "₹$1");
    text = text.replace(/([0-9,]+(?:\.[0-9]{2})?)\s*USD\b/gi, "₹$1");
    text = text.replace(/\bZAR\b/gi, "₹");
    text = text.replace(/\bUSD\b/gi, "₹");
    let html = escapeHtml(text);

    // Bold **text**
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic *text*
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    // Inline code `code`
    html = html.replace(/`(.*?)`/g, '<code class="bg-slate-100 text-slate-800 px-1 py-0.5 rounded text-xs">$1</code>');

    // Headers
    html = html.replace(/^### (.*$)/gim, '<h4 class="font-bold text-slate-900 text-base mt-2 mb-1">$1</h4>');
    html = html.replace(/^#### (.*$)/gim, '<h5 class="font-semibold text-slate-800 text-sm mt-2 mb-1">$1</h5>');

    // Bullet lists
    html = html.replace(/^\- (.*$)/gim, '<li class="ml-4 list-disc text-slate-700 my-0.5">$1</li>');

    // Tables simple parsing
    if (html.includes('|')) {
        const lines = html.split('\n');
        let inTable = false;
        let tableHtml = '<div class="overflow-x-auto my-2"><table class="w-full text-xs text-left border-collapse border border-slate-200">';
        let processedLines = [];

        for (let line of lines) {
            if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
                if (line.includes('---')) continue;
                inTable = true;
                const cells = line.split('|').filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
                tableHtml += '<tr class="border-b border-slate-100">';
                cells.forEach(c => {
                    tableHtml += `<td class="py-1 px-2 text-slate-700">${c.trim()}</td>`;
                });
                tableHtml += '</tr>';
            } else {
                if (inTable) {
                    tableHtml += '</table></div>';
                    processedLines.push(tableHtml);
                    inTable = false;
                }
                processedLines.push(line);
            }
        }
        if (inTable) {
            tableHtml += '</table></div>';
            processedLines.push(tableHtml);
        }
        html = processedLines.join('\n');
    }

    // Paragraphs / newlines
    html = html.replace(/\n\n/g, '<div class="h-2"></div>');
    html = html.replace(/\n/g, '<br/>');

    return html;
}
