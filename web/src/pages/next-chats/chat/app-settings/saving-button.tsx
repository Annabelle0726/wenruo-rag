import { ButtonLoading } from '@/components/ui/button';
import { useTranslation } from 'react-i18next';

type SaveButtonProps = {
  loading: boolean;
  /**
   * Id of the form this button submits. The drawer keeps its action row outside
   * the scrollable form, so the button has to name the form explicitly.
   */
  form?: string;
};

export function SavingButton({ loading, form }: SaveButtonProps) {
  const { t } = useTranslation();

  return (
    <ButtonLoading
      data-testid="chat-settings-save"
      type="submit"
      form={form}
      loading={loading}
    >
      {t('common.save')}
    </ButtonLoading>
  );
}
