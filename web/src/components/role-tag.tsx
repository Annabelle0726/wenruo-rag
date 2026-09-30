import { useTranslation } from 'react-i18next';

import { cn } from '@/lib/utils';
import { getRoleDisplayConfig } from '@/utils/tenant-role';

interface RoleTagProps {
  /** The caller's role, as returned by `GET /users/me`. */
  role?: string;
  className?: string;
}

/**
 * Read-only tag showing a tenant role.
 *
 * Styling comes from `getRoleDisplayConfig` so every role render in the app
 * shares one mapping. The SHAPE comes from `.settings-tag` — the settings
 * module's one tag geometry — plus that mapping's own tint, so a role tag, a
 * capability tag and a filter chip are the same object in three colours and a
 * column of roles cannot be three different heights. Every consumer of this
 * component is a settings surface.
 */
const RoleTag = ({ role, className }: RoleTagProps) => {
  const { t } = useTranslation();
  const { labelKey, badgeClass } = getRoleDisplayConfig(role);

  return (
    <span
      data-testid="role-tag"
      data-role={role ?? ''}
      className={cn('settings-tag', badgeClass, className)}
    >
      {t(labelKey)}
    </span>
  );
};

export default RoleTag;
