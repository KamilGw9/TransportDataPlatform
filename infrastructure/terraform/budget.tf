variable "alert_email" {
  type        = string
  description = "Address that receives the budget alerts."
}

# The host is expected to cost about 54 USD a month with the VAT, which the
# budget counts, so the alerts mean something unplanned is running.
resource "aws_budgets_budget" "monthly" {
  name         = "urban-mobility-monthly"
  budget_type  = "COST"
  limit_amount = "55"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Free plan credits would otherwise keep the measured cost at zero until
  # they run out, hiding how fast they are used.
  cost_types {
    include_credit = false
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
}
