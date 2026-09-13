#!/usr/bin/env python3
"""
Validate output.csv against requirements
"""

import csv
import sys
from decimal import Decimal

def validate_output():
    """Validate output.csv format and constraints."""
    
    errors = []
    warnings = []
    
    # Check if file exists
    try:
        with open('output.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except FileNotFoundError:
        print("❌ Error: output.csv not found!")
        return False
    
    # Check column names
    required_columns = [
        'request_id',
        'amount_safe_to_pay',
        'affordability_status',
        'recommended_payment_method',
        'payment_plan',
        'earliest_date_for_full_payment',
        'spending_changes_needed',
        'decision_explanation'
    ]
    
    if reader.fieldnames != required_columns:
        errors.append(f"Column mismatch. Expected: {required_columns}, Got: {reader.fieldnames}")
    
    # Load requests to check count
    with open('dataset/requests.csv', 'r', encoding='utf-8') as f:
        requests = list(csv.DictReader(f))
    
    if len(rows) != len(requests):
        errors.append(f"Row count mismatch. Expected {len(requests)} rows, got {len(rows)}")
    
    # Validate each row
    valid_statuses = {'affordable_now', 'affordable_with_plan', 'affordable_later', 'not_affordable'}
    valid_methods = {'full_payment', 'partial_payment', 'installments', 'wait', 'not_recommended'}
    
    for i, row in enumerate(rows, 1):
        request_id = row['request_id']
        
        # Find matching request
        request = next((r for r in requests if r['request_id'] == request_id), None)
        if not request:
            errors.append(f"Row {i}: Unknown request_id {request_id}")
            continue
        
        # Validate amount_safe_to_pay
        try:
            safe_amount = Decimal(row['amount_safe_to_pay'])
            requested_amount = Decimal(request['requested_amount'])
            
            if safe_amount < 0:
                errors.append(f"{request_id}: amount_safe_to_pay cannot be negative")
            
            if safe_amount > requested_amount:
                errors.append(f"{request_id}: amount_safe_to_pay ({safe_amount}) > requested_amount ({requested_amount})")
        except:
            errors.append(f"{request_id}: Invalid amount_safe_to_pay '{row['amount_safe_to_pay']}'")
        
        # Validate affordability_status
        if row['affordability_status'] not in valid_statuses:
            errors.append(f"{request_id}: Invalid affordability_status '{row['affordability_status']}'")
        
        # Validate recommended_payment_method
        if row['recommended_payment_method'] not in valid_methods:
            errors.append(f"{request_id}: Invalid recommended_payment_method '{row['recommended_payment_method']}'")
        
        # Validate affordable_now consistency
        if row['affordability_status'] == 'affordable_now':
            if row['earliest_date_for_full_payment'] != request['request_date']:
                warnings.append(f"{request_id}: affordable_now but earliest_date != request_date")
        
        # Validate payment_plan format
        if row['payment_plan'] != 'none':
            # Should be YYYY-MM-DD:amount|YYYY-MM-DD:amount
            if '|' in row['payment_plan']:
                payments = row['payment_plan'].split('|')
                for payment in payments:
                    if ':' not in payment:
                        errors.append(f"{request_id}: Invalid payment_plan format '{payment}'")
    
    # Print results
    print(f"\n{'='*60}")
    print(f"Validation Results")
    print(f"{'='*60}")
    print(f"Total rows: {len(rows)}")
    print(f"Expected rows: {len(requests)}")
    print(f"Errors: {len(errors)}")
    print(f"Warnings: {len(warnings)}")
    print(f"{'='*60}\n")
    
    if errors:
        print("❌ ERRORS:")
        for error in errors[:10]:  # Show first 10
            print(f"  - {error}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more")
        print()
    
    if warnings:
        print("⚠️  WARNINGS:")
        for warning in warnings[:10]:  # Show first 10
            print(f"  - {warning}")
        if len(warnings) > 10:
            print(f"  ... and {len(warnings) - 10} more")
        print()
    
    if not errors and not warnings:
        print("✅ All validations passed!")
        return True
    elif not errors:
        print("✅ No errors found (warnings can be ignored)")
        return True
    else:
        print("❌ Validation failed")
        return False

if __name__ == '__main__':
    success = validate_output()
    sys.exit(0 if success else 1)
