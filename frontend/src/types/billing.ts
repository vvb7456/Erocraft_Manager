export type PaymentChannel = 'alipay' | 'wechat'
export type OrderChannel = PaymentChannel | 'taobao' | 'xianyu' | 'other' | ''

const orderChannelColors: Record<OrderChannel, string> = {
  alipay: 'var(--green)',
  wechat: 'var(--green)',
  taobao: 'var(--amber)',
  xianyu: 'var(--amber)',
  other: 'var(--t3)',
  '': 'var(--t3)',
}

export function orderChannelColor(channel: OrderChannel): string {
  return orderChannelColors[channel]
}

export interface OrderInvoice {
  id: number
  invoice_no: string
  status: 'pending' | 'paid' | 'void'
  total_fen: number
  currency_code: string
  due_at: string | null
  paid_at: string | null
  gateway_code: PaymentChannel | null
}

export interface UserOrder {
  id: number
  order_no: string
  user_id: number
  plan_id: number | null
  plan_code: string
  plan_name: string
  kind: string
  period_count: number
  discount_pct: number
  total_fen: number
  total_days: number
  currency_code: string
  target_server_id: number | null
  target_server_name: string | null
  status: string
  received_fen: number
  refunded_fen: number
  created_at: string
  updated_at: string
  applied_at: string | null
  closed_at: string | null
  cancelled_at: string | null
  invoice: OrderInvoice | null
  coupon_id: number | null
  coupon_code: string | null
  coupon_discount_fen: number | null
}
