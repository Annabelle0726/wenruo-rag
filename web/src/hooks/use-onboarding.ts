import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import onboardingService, {
  InvitationMetadata,
} from '@/services/onboarding-service';
import authorizationUtil from '@/utils/authorization-util';
import { setActiveTenantId } from '@/utils/active-tenant';
import { rsaPsw } from '@/utils';

const OnboardingKeys = {
  invitation: (token: string) => ['invitation', token] as const,
};

export const useInvitation = (token: string) => {
  const client = useQueryClient();
  const metadata = useQuery({
    queryKey: OnboardingKeys.invitation(token),
    enabled: /^[a-f0-9]{32}$/.test(token),
    retry: false,
    gcTime: 0,
    queryFn: async (): Promise<InvitationMetadata> => {
      const { data } = await onboardingService.metadata(
        { token, skipToken: true },
        true,
      );
      if (data.code !== 0) throw new Error(data.message);
      return data.data;
    },
  });
  const accept = useMutation({
    mutationFn: async ({
      nickname,
      password,
    }: {
      nickname: string;
      password: string;
    }) => {
      const response = await onboardingService.accept(
        {
          token,
          skipToken: true,
          data: { nickname, password: await rsaPsw(password) },
        },
        true,
      );
      if (response.data.code !== 0) return false;
      const auth = response.headers.authorization;
      if (typeof auth !== 'string' || !auth)
        throw new Error('Missing authorization');
      const user = response.data.data;
      authorizationUtil.removeAll();
      authorizationUtil.setAuthorization(auth);
      authorizationUtil.setUserInfo({
        name: user.nickname,
        email: user.email,
        avatar: user.avatar,
      });
      setActiveTenantId(user.current_tenant_id);
      client.clear();
      return true;
    },
  });
  return { metadata, accept };
};

export const usePasswordRecovery = () => {
  const sendCode = useMutation({
    mutationFn: async (email: string) => {
      const { data } = await onboardingService.sendResetCode({ email });
      return data.code === 0;
    },
  });
  const reset = useMutation({
    mutationFn: async ({
      email,
      code,
      password,
    }: {
      email: string;
      code: string;
      password: string;
    }) => {
      const { data } = await onboardingService.resetPassword({
        email,
        code,
        newPassword: await rsaPsw(password),
      });
      return data.code === 0;
    },
  });
  return { sendCode, reset };
};
