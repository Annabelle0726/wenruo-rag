import { registerNextServer } from '@/utils/register-server';

export interface InvitationResult {
  joined: boolean;
  invite_path?: string;
}

export interface InvitationMetadata {
  tenant_name: string;
  email: string;
  role: 'normal' | 'admin';
  department_name: string | null;
}

const onboardingService = registerNextServer({
  invite: {
    url: ({ tenantId }: { tenantId: string }) =>
      `/api/v1/tenants/${encodeURIComponent(tenantId)}/invitations`,
    method: 'post',
  },
  metadata: {
    url: ({ token }: { token: string }) =>
      `/api/v1/invitations/${encodeURIComponent(token)}`,
    method: 'get',
  },
  accept: {
    url: ({ token }: { token: string }) =>
      `/api/v1/invitations/${encodeURIComponent(token)}/accept`,
    method: 'post',
  },
  sendResetCode: { url: '/api/v1/auth/reset-password-code', method: 'post' },
  resetPassword: { url: '/api/v1/auth/reset-password', method: 'post' },
});

export default onboardingService;
