export interface CreditRequest {
  request_id: string
  amount: string
  reason: string
}

export interface BalanceCredit {
  id: number
  request_id: string
  user_id: number
  admin_id: number
  amount: number
  balance_before: number
  balance_after: number
  reason: string
  created_at: string
}

export interface CreditHistory {
  items: BalanceCredit[]
  total: number
}
