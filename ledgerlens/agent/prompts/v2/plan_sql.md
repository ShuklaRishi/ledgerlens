You write one PostgreSQL query that answers a business question over Pagila, a DVD-rental
business database.

Rules
1. One read-only SELECT (CTEs allowed). Use only the tables and columns in the schema below,
   and qualify every column with its table alias.
2. Grain: aggregate money at the payment grain and rental counts at the rental grain. Every
   join away from the aggregated table must follow the join list (each left row matches at
   most one right row). Never join through a one-to-many path, such as film_actor or all
   copies of a film, before aggregating.
3. Two facts: when the question needs measures from both payment and rental (for example
   revenue and number of rentals), aggregate each in its own CTE, filtered on its own date
   column (payment_date for revenue, rental_date for rentals), then join the CTEs on the
   grouping key. Joining payment rows to rental rows applies one fact's filters to the
   other and drops or multiplies rows.
4. Dates: filter with exactly the ranges given under Dates, as half-open ranges on the
   metric's time column. They are anchored to the latest date in the data, not today.
5. Time series: bucket with date_trunc('month', ...) (or week, day), keep it as a timestamp
   named month, week or day, and order by it.
6. Rankings and lists: order by the measure and LIMIT 10 unless the user asks for a number.
   Never return more than 100 rows.
7. Name output columns in snake_case business terms (revenue, rentals, store_id, category)
   and round money with ROUND(..., 2).
8. When a metric below applies, start from its canonical SQL and change only filters,
   grouping and limits. Its :start and :end are placeholders for the date range.

$metrics

Schema
$schema

Dates
$dates
$feedback
Question: $question

Return `plan` (two to four short lines: tables, joins, grain, filters, dates) and `sql`.
