import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal/modal';
import message from '@/components/ui/message';
import { usePasswordRecovery } from '@/hooks/use-onboarding';
import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

export default function PasswordRecovery() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [sent, setSent] = useState(false);
  const { sendCode, reset } = usePasswordRecovery();
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    event.stopPropagation();
    try {
      if (!sent) {
        if (await sendCode.mutateAsync(email)) {
          setSent(true);
          message.success(t('onboarding.codeSent'));
        }
      } else if (await reset.mutateAsync({ email, code, password })) {
        message.success(t('onboarding.resetDone'));
        setOpen(false);
        setPassword('');
        setCode('');
        setSent(false);
      }
    } catch {
      /* Request layer displays transport errors. */
    }
  };
  const resend = async () => {
    try {
      if (await sendCode.mutateAsync(email))
        message.success(t('onboarding.codeSent'));
    } catch {
      /* Request layer displays transport errors. */
    }
  };
  const show = () => {
    setSent(false);
    setCode('');
    setPassword('');
    setOpen(true);
  };
  return (
    <>
      <Button
        type="button"
        variant="ghost"
        className="h-auto shrink-0 whitespace-nowrap px-0 py-1 text-sm text-text-secondary hover:text-accent-color"
        onClick={show}
      >
        {t('onboarding.forgot')}
      </Button>
      <Modal
        open={open}
        onOpenChange={setOpen}
        title={t('onboarding.forgot')}
        showfooter={false}
      >
        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            {t('setting.email')}
            <Input
              type="email"
              required
              autoComplete="email"
              value={email}
              readOnly={sent}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          {sent && (
            <>
              <label className="block">
                {t('onboarding.code')}
                <Input
                  required
                  pattern="[0-9]{6}"
                  maxLength={6}
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  value={code}
                  onChange={(event) => setCode(event.target.value)}
                />
              </label>
              <label className="block">
                {t('onboarding.newPassword')}
                <Input
                  type="password"
                  required
                  minLength={8}
                  maxLength={128}
                  autoComplete="new-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                />
              </label>
              <Button
                type="button"
                variant="ghost"
                disabled={sendCode.isPending}
                onClick={resend}
              >
                {t('onboarding.sendCode')}
              </Button>
            </>
          )}
          <Button
            type="submit"
            disabled={sendCode.isPending || reset.isPending}
          >
            {t(sent ? 'onboarding.reset' : 'onboarding.sendCode')}
          </Button>
        </form>
      </Modal>
    </>
  );
}
