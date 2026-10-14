export const emailTemplateKeys = [
  'bulk', 'reminder', 'expired', 'preDelete', 'createUser', 'passwordReset',
  'emailChange', 'registerVerify', 'alertFired', 'alertResolved',
  'orderPaid', 'orderApplyFailed', 'orderApplyAlert', 'orderRefunded',
  'serverInstalled', 'referralInviterRewarded', 'referralInviteeRewarded',
] as const

export type EmailTemplateKey = typeof emailTemplateKeys[number]
