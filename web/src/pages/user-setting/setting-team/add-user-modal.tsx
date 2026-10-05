/*
 *  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
 *
 *  Licensed under the Apache License, Version 2.0 (the "License");
 *  you may not use this file except in compliance with the License.
 *  You may obtain a copy of the License at
 *
 *      http://www.apache.org/licenses/LICENSE-2.0
 *
 *  Unless required by applicable law or agreed to in writing, software
 *  distributed under the License is distributed on an "AS IS" BASIS,
 *  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 *  See the License for the specific language governing permissions and
 *  limitations under the License.
 */

import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from '@/components/ui/form';
import { CopyToClipboard } from 'react-copy-to-clipboard';
import { Button } from '@/components/ui/button';
import message from '@/components/ui/message';
import { Input } from '@/components/ui/input';
import { Modal } from '@/components/ui/modal/modal';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { IModalProps } from '@/interfaces/common';
import DepartmentSelect from './department-select';
import { zodResolver } from '@hookform/resolvers/zod';
import { useForm } from 'react-hook-form';
import { useTranslation } from 'react-i18next';
import * as z from 'zod';
import { TenantRole } from '../constants';

/**
 * The invite dialog's card: the glass surface at the translucent token, a 24px
 * backdrop blur, the hairline edge and the drawer shadow.
 *
 * Four of these classes carry the important modifier because `Modal`
 * interpolates `className` in the *middle* of its own class list, so
 * tailwind-merge reads the primitive's `bg-bg-base`, `rounded-lg`,
 * `border-border-default` and `shadow-lg` as the later ones and keeps both
 * sides; without the modifier the card stays an opaque page-coloured slab with
 * the default grey edge, which is what the rendered dialog measured before.
 */
const DialogCardClassName =
  'glass-panel !rounded-2xl !border-cable-hairline !bg-glass backdrop-blur-xl !shadow-cable-drawer';

/**
 * The dialog actions. One flex row each, so the label sits on the icon's centre
 * line and can never wrap, and an edge from a token so neither action is a
 * borderless block: the accent-confirm pill takes the real line token
 * (`--badge-border` composites into the accent fill itself in dark mode, so it
 * would not read as an edge there), the secondary cancel capsule the hairline
 * `.ceramic-relief` already draws.
 */
const ConfirmButtonClassName =
  'ceramic-cta inline-flex h-10 items-center justify-center whitespace-nowrap rounded-xl border border-[var(--field-border)] bg-accent-color px-5 text-accent-contrast hover:bg-accent-color-strong';

const CancelButtonClassName =
  'ceramic-relief inline-flex h-10 items-center justify-center whitespace-nowrap rounded-full px-4 text-text-secondary hover:bg-glass hover:text-state-error';

const AddingUserModal = ({
  visible,
  hideModal,
  loading,
  onOk,
  invitePath,
}: IModalProps<{
  email: string;
  role?: string;
  departmentId?: string | null;
  title?: string | null;
}> & { invitePath?: string }) => {
  const { t } = useTranslation();

  const formSchema = z.object({
    email: z
      .string()
      .email()
      .min(1, { message: t('common.required') }),
    role: z.string().default('normal'),
    // An empty string is the "no department" choice: a Select cannot hold null.
    departmentId: z.string().default(''),
  });

  type FormData = z.infer<typeof formSchema>;

  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      email: '',
      role: TenantRole.Normal,
      departmentId: '',
    },
  });

  const handleOk = async (data: FormData) => {
    return onOk?.({
      email: data.email,
      role: data.role,
      departmentId: data.departmentId || null,
    });
  };

  const inviteUrl = invitePath ? window.location.origin + invitePath : '';
  const copyLink = (_text: string, result: boolean) => {
    if (result) message.success(t('onboarding.copied'));
    else message.error(t('onboarding.copyFailed'));
  };

  return (
    <Modal
      title={t(invitePath ? 'onboarding.linkReady' : 'setting.add')}
      open={visible || false}
      onOpenChange={(open) => !open && hideModal?.()}
      onOk={form.handleSubmit(handleOk)}
      showfooter={!invitePath}
      confirmLoading={loading}
      okText={t('common.ok')}
      cancelText={t('common.cancel')}
      className={DialogCardClassName}
      okButtonClassName={ConfirmButtonClassName}
      cancelButtonClassName={CancelButtonClassName}
    >
      {invitePath ? (
        <div className="min-w-0 space-y-4">
          <p className="text-sm leading-relaxed text-text-secondary">
            {t('onboarding.linkHint')}
          </p>
          <Input
            className="ceramic-field h-11 w-full min-w-0 text-sm"
            aria-label={t('onboarding.linkReady')}
            value={inviteUrl}
            readOnly
          />
          <CopyToClipboard text={inviteUrl} onCopy={copyLink}>
            <Button className="ceramic-cta h-10 w-full sm:w-auto">
              {t('onboarding.copy')}
            </Button>
          </CopyToClipboard>
        </div>
      ) : (
        <Form {...form}>
          <form onSubmit={form.handleSubmit(handleOk)} className="space-y-4">
            <FormField
              control={form.control}
              name="email"
              render={({ field }) => (
                <FormItem>
                  <FormLabel required>{t('setting.email')}</FormLabel>
                  <FormControl>
                    <Input
                      className="ceramic-field h-11"
                      placeholder={t('setting.email')}
                      {...field}
                    />
                  </FormControl>
                  <FormDescription className="text-xs">
                    {t('setting.inviteTip')}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="role"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('setting.role')}</FormLabel>
                  <Select value={field.value} onValueChange={field.onChange}>
                    <FormControl>
                      <SelectTrigger className="ceramic-field h-11">
                        <SelectValue />
                      </SelectTrigger>
                    </FormControl>
                    <SelectContent>
                      <SelectItem value={TenantRole.Normal}>
                        {t('setting.roleMember')}
                      </SelectItem>
                      <SelectItem value={TenantRole.Admin}>
                        {t('setting.roleAdmin')}
                      </SelectItem>
                    </SelectContent>
                  </Select>
                  <FormDescription className="text-xs">
                    {t('setting.inviteRoleTip')}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
            <FormField
              control={form.control}
              name="departmentId"
              render={({ field }) => (
                <FormItem>
                  <FormLabel>{t('setting.department')}</FormLabel>
                  <FormControl>
                    <DepartmentSelect
                      value={field.value}
                      onChange={(departmentId) =>
                        field.onChange(departmentId ?? '')
                      }
                      testId="invite-department"
                    />
                  </FormControl>
                  <FormDescription className="text-xs">
                    {t('setting.departmentTip')}
                  </FormDescription>
                  <FormMessage />
                </FormItem>
              )}
            />
          </form>
        </Form>
      )}
    </Modal>
  );
};

export default AddingUserModal;
