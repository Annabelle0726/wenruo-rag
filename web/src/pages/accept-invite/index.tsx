import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useInvitation } from '@/hooks/use-onboarding';
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useSearchParams } from 'react-router';

export default function AcceptInvite() {
  const { t } = useTranslation();
  const [params] = useSearchParams();
  const token = params.get('token') || '';
  const { metadata, accept } = useInvitation(token);
  const [nickname, setNickname] = useState('');
  const [password, setPassword] = useState('');
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      if (await accept.mutateAsync({ nickname, password }))
        window.location.replace('/');
    } catch {
      /* Request layer displays transport errors. */
    }
  };
  return (
    <main className="min-h-dvh bg-bg-base text-text-primary flex items-center justify-center px-4 py-8 sm:px-6">
      <section className="ceramic-pill w-full min-w-0 max-w-[520px] space-y-5 px-6 py-7 sm:px-8">
        <h1 className="text-center text-2xl font-semibold">
          {t('onboarding.acceptTitle')}
        </h1>
        {metadata.isFetching ? (
          <p>{t('common.loading')}</p>
        ) : metadata.data ? (
          <>
            <p className="break-words text-sm leading-relaxed text-text-secondary">
              {t('onboarding.welcome', {
                tenant: metadata.data.tenant_name,
                department:
                  metadata.data.department_name || t('onboarding.noDepartment'),
              })}
            </p>
            <p className="break-all text-sm text-text-secondary">
              {metadata.data.email} ·{' '}
              {t(
                metadata.data.role === 'admin'
                  ? 'setting.roleAdmin'
                  : 'setting.roleMember',
              )}
            </p>
            <form className="space-y-4" onSubmit={submit}>
              <label className="block space-y-2 text-sm font-medium">
                {t('login.nicknameLabel')}
                <Input
                  className="focus-glow h-10 px-4"
                  value={nickname}
                  onChange={(event) => setNickname(event.target.value)}
                  required
                  maxLength={100}
                  autoComplete="nickname"
                />
              </label>
              <label className="block space-y-2 text-sm font-medium">
                {t('login.passwordLabel')}
                <Input
                  className="focus-glow h-10 px-4"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  type="password"
                  required
                  minLength={8}
                  maxLength={128}
                  autoComplete="new-password"
                />
              </label>
              <Button
                type="submit"
                className="ceramic-cta h-10 w-full"
                disabled={accept.isPending}
              >
                {t('onboarding.accept')}
              </Button>
            </form>
          </>
        ) : (
          <p role="alert">{t('onboarding.invalid')}</p>
        )}
        <Link
          className="block text-center text-sm text-text-secondary hover:text-accent-color"
          to="/login"
        >
          {t('onboarding.backToLogin')}
        </Link>
      </section>
    </main>
  );
}
