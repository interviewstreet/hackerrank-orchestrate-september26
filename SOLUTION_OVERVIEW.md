# Solution Overview: Buy or Wait?

## Executive Summary

This AI-powered financial decision agent uses Claude 3.5 Sonnet to analyze user financial situations and provide personalized affordability recommendations. The solution comprehensively considers balance, recurring expenses, income patterns, payment preferences, and contextual information from messages and images.

## Architecture

### High-Level Flow

```
Input Data → Context Building → AI Analysis → Output Generation
```

1. **Input Data Loading**: Load all CSV files and images from dataset/
2. **Context Building**: For each request, gather user profile, events, messages, images, and payment options
3. **AI Analysis**: Use Claude 3.5 Sonnet to analyze and make recommendations
4. **Output Generation**: Format results into required CSV schema

### Key Components

#### 1. Data Loader
- Loads 7 CSV files with financial data
- Handles date parsing and decimal conversion
- Links related records via IDs

#### 2. Context Builder
- Assembles comprehensive financial picture per request
- Extracts amounts from images using Claude Vision when needed
- Includes recent 6 months of history + future events
- Filters relevant messages and payment options

#### 3. AI Decision Engine
- Prompts Claude 3.5 Sonnet with structured context
- Requests JSON output with all required fields
- Uses temperature=0 for deterministic decisions
- Handles edge cases and validates constraints

#### 4. Output Formatter
- Validates JSON responses
- Formats into required CSV schema
- Handles fallbacks for errors
- Tracks token usage

## Decision Logic

The AI is instructed to follow these principles:

### 1. Cash Flow Forecasting
- Identify recurring income from historical patterns
- Detect recurring expenses (rent, utilities, subscriptions)
- Account for pending transactions (only settled income counts)
- Project 90-day balance trajectory

### 2. Safety Checks
- Balance must never drop below `minimum_balance_to_keep`
- Protected categories cannot be reduced/stopped
- Only flexible expenses can be adjusted
- Confirmed income only (pending bonuses don't count)

### 3. Payment Method Selection
Priority order:
1. Complete by desired deadline
2. Avoid spending changes
3. Minimize total payment cost
4. Start payment earlier
5. Use fewer payments

**Full Payment**: Pay entire amount today if safe

**Partial Payment**: 
- Only if request allows it
- User accepts partial payment
- Two payments: partial today + remainder on earliest safe date
- Must complete by deadline

**Installments**:
- Must match exactly one supplied payment option
- User willing to consider installments
- Number of payments ≤ max_installment_months
- Keeps balance above minimum throughout

**Wait**:
- Full payment becomes safe later
- User accepts full payment method
- Within forecast period

**Not Recommended**:
- No safe option exists
- Or user unwilling to use available options

### 4. Context Integration

**Messages**: 
- Salary changes/confirmations
- Pending/cancelled transactions
- Contract updates
- Payment delays

**Images**:
- Extract amounts for events with blank amount field
- Payslips, statements, receipts, bills
- Use Claude Vision for OCR

### 5. Conflict Resolution
When data conflicts:
1. Explicit cancellation/amendment wins
2. Newer record from same source
3. Settled over estimated
4. Financially safer interpretation

## Technical Decisions

### Why Claude 3.5 Sonnet?

**Strengths:**
- 200K context window (fits full financial history)
- Excellent reasoning for complex financial decisions
- Multimodal (text + images)
- Reliable JSON structured output
- Strong at following detailed instructions

**Trade-offs:**
- Higher cost per request (~$0.05-0.15 each)
- Requires API access
- Processing time (1-3 seconds per request)

### Alternative Approaches Considered

#### 1. Rules-Based System
**Pros**: Fast, cheap, deterministic
**Cons**: Brittle, hard to handle edge cases, requires extensive coding

#### 2. Hybrid (Rules + AI)
**Pros**: Cost-effective, handles simple cases fast
**Cons**: More complexity, harder to maintain

#### 3. Fine-tuned Model
**Pros**: Potentially cheaper at scale, faster
**Cons**: Requires training data, less flexible, harder to iterate

**Decision**: Pure AI approach for this hackathon because:
- 24-hour time constraint favors rapid iteration
- 250 requests is manageable with API
- Complex domain benefits from reasoning capability
- Easier to debug and improve via prompts

### Prompt Engineering Strategy

The prompt includes:
1. **Role**: "Expert financial advisor"
2. **Context**: All relevant data structured clearly
3. **Task**: Specific decision requirements
4. **Constraints**: Critical rules and validations
5. **Format**: Exact JSON schema expected
6. **Examples**: Implicit via detailed instructions

Key techniques:
- Temperature=0 for consistency
- Structured data sections (profile, events, messages, options)
- Explicit constraint listing
- JSON schema with field descriptions
- "Return ONLY valid JSON" instruction

## Data Processing

### Event Classification

**Settled**: Completed transactions, count toward balance
**Pending**: Reserved funds, deduct from available
**Scheduled**: Future confirmed payments
**Failed/Cancelled**: Ignore
**Unrealized**: Investment values, don't count as cash

### Recurrence Detection

Pattern indicators:
- Same description repeating monthly
- Same category and amount
- Regular date pattern (e.g., 1st, 15th)
- Marked as "recurring" in flexibility

The AI identifies these patterns from historical data.

### Currency Handling

All amounts normalized to user's home currency:
- Use exchange_rates.csv for conversions
- Match by settlement_date and currency pair
- Output amounts in home currency

## Error Handling

### Graceful Degradation

1. **Image extraction fails**: Skip amount, rely on other context
2. **AI call fails**: Return safe default (not_recommended)
3. **Invalid JSON**: Log warning, use fallback
4. **Missing context**: Process with available data

### Validation

Post-processing checks:
- amount_safe_to_pay ≤ requested_amount
- Payment plan matches chosen method
- Installments match supplied options
- Spending changes reference flexible events
- All required fields populated

## Performance Characteristics

### Expected Token Usage

Per request:
- Input: 2,000-4,000 tokens (depends on history length)
- Output: 200-500 tokens

Total for 250 requests:
- Input: ~500K-1M tokens
- Output: ~50K-125K tokens
- Cost: ~$10-25

### Processing Time

- Sequential: ~8-12 minutes (250 requests × 2-3 sec each)
- Could parallelize for faster processing

## Testing Strategy

### Validation Against Samples

1. Process the 25 sample_requests.csv
2. Compare outputs to provided solutions
3. Check for:
   - Exact amount matches
   - Status consistency
   - Method correctness
   - Plan format validity

### Edge Cases to Verify

- Zero balance requests
- Conflicting messages
- Missing image amounts
- User with no income
- All payment methods rejected by user
- Requests with impossible deadlines

## Improvements for Production

### Short-term Enhancements

1. **Batch Processing**: Process multiple requests per API call
2. **Caching**: Cache recurring patterns per user
3. **Validation Layer**: Add post-processing constraint checker
4. **Retry Logic**: Handle transient API failures
5. **Parallel Processing**: Use async for faster execution

### Long-term Enhancements

1. **Hybrid Approach**: Rules for simple cases, AI for complex
2. **Model Comparison**: A/B test multiple models
3. **Fine-tuning**: Train on domain-specific examples
4. **Self-Verification**: AI validates its own output
5. **Confidence Scores**: Flag uncertain predictions
6. **Explainability**: Detailed reasoning trace
7. **User Feedback Loop**: Learn from corrections

## Known Limitations

1. **Determinism**: AI may give slightly different answers on reruns (mitigated with temperature=0)
2. **Cost**: Scales linearly with request count
3. **Dependencies**: Requires API access and key
4. **Recurrence Detection**: Relies on AI pattern recognition rather than explicit rules
5. **Image Quality**: OCR accuracy depends on image clarity

## Conclusion

This solution prioritizes:
- **Accuracy**: Comprehensive context and strong reasoning
- **Completeness**: Handles all required output fields
- **Robustness**: Graceful error handling
- **Maintainability**: Clear prompt-based logic
- **Speed of Development**: Rapid iteration during hackathon

Trade-offs favor quality over cost/speed given the 24-hour constraint and 250-request scale.
