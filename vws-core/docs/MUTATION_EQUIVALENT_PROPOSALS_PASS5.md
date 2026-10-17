# Pass 5 individual equivalent proposals

Baseline: e09684a. These are proposals, not approvals. The six-entry equivalent
list is unchanged; all six IDs below continue to fail the mutation gate.
No reachable error-message change is being dismissed as diagnostic-only.

## backend.execution.alpaca_executor.xǁExactLimitǁto_request_fields__mutmut_4

```diff
-            raise DataIntegrityError("Validated order has no side")
+            raise DataIntegrityError(None)
```

The changed statement is unreachable: `ExactLimit.model_validate(self)` runs
first, including SDK side validation and `allowed_shape`. The only accepted
classes are BRACKET/OTO (BUY), OCO (SELL), or SIMPLE/None (SELL). MLEG and all
other classes are rejected. Thus a successful validation always has a side.
The new four-shape no-side tests exercise refusal before serialization,
including a `model_copy` that bypassed validation when it was made.

## backend.execution.alpaca_executor.xǁExactLimitǁto_request_fields__mutmut_5

```diff
-            raise DataIntegrityError("Validated order has no side")
+            raise DataIntegrityError("XXValidated order has no sideXX")
```

No input reaches this message: revalidation requires BUY for BRACKET/OTO and
SELL for OCO/SIMPLE, and rejects other classes. The no-side rejection tests
exercise all four accepted shapes. This proposal relies on the unreachable
statement, not on treating reachable message text as equivalent.

## backend.execution.alpaca_executor.xǁExactLimitǁto_request_fields__mutmut_6

```diff
-            raise DataIntegrityError("Validated order has no side")
+            raise DataIntegrityError("validated order has no side")
```

No input reaches this statement after the mandatory SDK/model revalidation:
each accepted order class requires an explicit BUY or SELL side. A malformed
instance made with `model_copy` is revalidated and refused first. The changed
message therefore cannot become observable with any accepted or refused input.

## backend.execution.alpaca_executor.xǁExactLimitǁto_request_fields__mutmut_7

```diff
-            raise DataIntegrityError("Validated order has no side")
+            raise DataIntegrityError("VALIDATED ORDER HAS NO SIDE")
```

The preceding mandatory model validation rejects every missing-side instance
before this statement. Every accepted BRACKET/OTO requires BUY, every accepted
OCO/SIMPLE requires SELL, and other order classes are rejected. This includes
objects constructed with validation bypasses, because serialization revalidates
them. The uppercased message cannot be emitted for any reachable input.

## backend.execution.alpaca_executor.xǁExactLimitǁto_request_fields__mutmut_48

Exact changed dictionary value (all other entries are unchanged):

```diff
-            "limit_price": format(checked.limit_price, ".2f"),
+            "limit_price": format(checked.limit_price, ),
```

`Price` revalidation calls `validate_cent_price`, which rejects nonfinite,
nonpositive, out-of-bound and sub-cent values and returns the Decimal quantized
to exponent -2. The empty Decimal format and `.2f` therefore produce the same
ordinary fixed-point text for every reachable price. OCO removes this entry in
both versions. Exact four-shape wire-dictionary tests assert cent text.

## backend.execution.alpaca_executor.xǁExactLimitǁto_request_fields__mutmut_50

Exact changed dictionary value (all other entries are unchanged):

```diff
-            "limit_price": format(checked.limit_price, ".2f"),
+            "limit_price": format(checked.limit_price, ".2F"),
```

Every reachable `Price` is a finite positive Decimal, revalidated and quantized
to cents. Decimal `f` versus `F` changes the case of nonfinite spellings; finite
fixed-point digits and punctuation are identical. Nonfinite inputs are rejected
before this call. OCO deletes the value in both versions.

## Required-coverage consequence

There were no individual exclusions for the thirteen previously unselected
executor functions. The approved coverage inclusion adds the executor module.
It also exposes the unreachable missing-side guard at alpaca_executor.py:213.
The 100% threshold remains unchanged. These proposals do not exclude that line,
change a coverage result, authorize source removal, or claim a passing gate.
