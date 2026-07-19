/**
 * Default placeholder bodies for the two fixed user agreements (tos /
 * privacy). Used as a fallback when the backend has no published
 * version yet (current_version == 0) or returns an empty body — the
 * UI treats an agreement as always present, never shows an "empty"
 * state, and renders this sample text instead.
 *
 * Admins are expected to overwrite these via the management UI; until
 * they do, users see a minimal placeholder so the register flow is
 * never blocked by missing content.
 */

export const DEFAULT_AGREEMENT_BODIES: Record<'tos' | 'privacy', {
  zh: string
  en: string
}> = {
  tos: {
    zh: [
      '# 用户服务协议',
      '',
      '> 这是占位示例文本。管理员尚未发布正式协议正文，请前往后台「设置 → 用户协议」编辑后保存。',
      '',
      '## 1. 服务范围',
      '',
      '本服务由平台运营方提供，具体内容以平台实际展示为准。',
      '',
      '## 2. 用户义务',
      '',
      '- 遵守相关法律法规；',
      '- 不得滥用本服务，不得从事任何违法违规活动；',
      '- 妥善保管账户凭证，因账户泄露造成的损失由用户自行承担。',
      '',
      '## 3. 变更与终止',
      '',
      '平台保留在法律允许范围内修改、中止或终止本服务的权利。',
    ].join('\n'),
    en: [
      '# Terms of Service',
      '',
      '> This is placeholder sample text. The administrator has not yet published the official agreement body. Please edit and save it in **Settings → User Agreements**.',
      '',
      '## 1. Scope of Service',
      '',
      'This service is provided by the platform operator. The exact scope is subject to what the platform actually presents.',
      '',
      '## 2. User Obligations',
      '',
      '- Comply with applicable laws and regulations;',
      '- Do not abuse this service or engage in any illegal activity;',
      '- Safeguard your account credentials; you are responsible for losses caused by credential leakage.',
      '',
      '## 3. Changes and Termination',
      '',
      'The platform reserves the right to modify, suspend, or terminate this service within the limits permitted by law.',
    ].join('\n'),
  },
  privacy: {
    zh: [
      '# 隐私政策',
      '',
      '> 这是占位示例文本。管理员尚未发布正式政策正文，请前往后台「设置 → 用户协议」编辑后保存。',
      '',
      '## 1. 收集的信息',
      '',
      '为提供服务，平台会收集必要的账户信息（用户名、邮箱）及使用日志。',
      '',
      '## 2. 信息使用',
      '',
      '- 用于身份验证与服务交付；',
      '- 用于安全审计与异常排查；',
      '- 不会向第三方出售或共享您的个人信息。',
      '',
      '## 3. 信息存储与保护',
      '',
      '平台采取合理的技术与管理措施保护您的信息安全。',
      '',
      '## 4. 联系方式',
      '',
      '如对隐私政策有任何疑问，请通过平台公布的渠道联系运营方。',
    ].join('\n'),
    en: [
      '# Privacy Policy',
      '',
      '> This is placeholder sample text. The administrator has not yet published the official policy body. Please edit and save it in **Settings → User Agreements**.',
      '',
      '## 1. Information We Collect',
      '',
      'To provide the service, the platform collects necessary account information (username, email) and usage logs.',
      '',
      '## 2. How We Use Information',
      '',
      '- For authentication and service delivery;',
      '- For security auditing and incident response;',
      '- We do not sell or share your personal information with third parties.',
      '',
      '## 3. Storage and Protection',
      '',
      'The platform takes reasonable technical and organizational measures to protect your information.',
      '',
      '## 4. Contact',
      '',
      'For any questions about this privacy policy, please contact the operator via the channels published by the platform.',
    ].join('\n'),
  },
}

/**
 * Resolve the body for display: fall back to the default placeholder
 * when the backend returned an empty string. ``slug`` must be 'tos' or
 * 'privacy'; unknown slugs return the tos placeholder as a safe default.
 */
export function resolveAgreementBody(
  slug: string,
  body: string,
  locale: 'zh' | 'en',
): string {
  if (body && body.trim()) return body
  const key = (slug === 'privacy' ? 'privacy' : 'tos') as 'tos' | 'privacy'
  return DEFAULT_AGREEMENT_BODIES[key][locale]
}

/**
 * Fixed display name for a fixed slug, driven by the i18n keys used on
 * the register page. Returns the slug itself when called with an
 * unexpected value (defensive — should not happen in practice).
 */
export const FIXED_AGREEMENT_SLUGS = ['tos', 'privacy'] as const
export type FixedAgreementSlug = (typeof FIXED_AGREEMENT_SLUGS)[number]
