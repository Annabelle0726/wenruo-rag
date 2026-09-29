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

import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import { TooltipProvider } from '@/components/ui/tooltip';
import { TenantRole } from '@/pages/user-setting/constants';
import UserSettingTeam from '../index';

/**
 * What the team page must show, per role, for the workspace the caller is
 * actually in - and which roster controls it must not show at all, because the
 * server refuses them (`PUT .../role` rejects the caller's own row; a NORMAL
 * member fails `_require_manager`). Hiding a control that would come back as
 * `code=108` is the point here; the guards themselves live in the API.
 */

interface ITestMember {
  user_id: string;
  nickname: string;
  email: string;
  role: string;
  is_owner: boolean;
  update_date: string;
}

interface ITestTenant {
  tenant_id: string;
  /** The workspace's own name; `nickname` belongs to its owner. */
  name?: string | null;
  nickname: string;
  email: string;
  role: string;
  is_active: boolean;
  update_date: string;
}

let mockUser: { id: string; nickname: string; role?: string };
let mockTenantInfo: { tenant_id: string; name?: string };
let mockRoster: ITestMember[];
let mockTenants: ITestTenant[];
let mockSetActiveTenant: jest.Mock;
let mockUpdateTenantUserRole: jest.Mock;
let mockDeleteTenantUser: jest.Mock;

jest.mock('@/hooks/use-user-setting-request', () => ({
  useFetchUserInfo: () => ({ data: mockUser }),
  useFetchTenantInfo: () => ({ data: mockTenantInfo }),
  useListTenantUser: () => ({ data: mockRoster, loading: false }),
  useListTenant: () => ({ data: mockTenants, loading: false }),
  useListDepartments: () => ({ data: [], loading: false }),
  useUpdateTenantUserRole: () => ({
    updateTenantUserRole: mockUpdateTenantUserRole,
  }),
  useUpdateTenantUserProfile: () => ({
    updateTenantUserProfile: jest.fn(),
  }),
  useDeleteTenantUser: () => ({
    deleteTenantUser: mockDeleteTenantUser,
    loading: false,
  }),
  useAgreeTenant: () => ({ agreeTenant: jest.fn(), loading: false }),
  useSetActiveTenant: () => ({
    setActiveTenant: mockSetActiveTenant,
    loading: false,
  }),
  useAddTenantUser: () => ({ addTenantUser: jest.fn(), loading: false }),
  useDepartmentMutations: () => ({
    create: jest.fn(),
    rename: jest.fn(),
    remove: jest.fn(),
  }),
}));

// The workspace quota section reads its numbers from `GET /tenants/<id>/usage/quota`
// through React Query, so without this mock the page under test needs a
// `QueryClientProvider` and a live request that this suite has no business making.
// `UsagePolicySection` renders its "budget unavailable" panel for that empty
// answer, which is how a manager sees the page when the backend has no budget row
// yet; the roster controls this suite is about are unaffected.
jest.mock('@/hooks/use-workspace-usage-request', () => ({
  useFetchQuotaStatus: () => ({ data: undefined, loading: false }),
}));

const member = (
  user_id: string,
  role: string,
  nickname: string,
  is_owner = false,
): ITestMember => ({
  user_id,
  nickname,
  email: `${user_id}@example.com`,
  role,
  is_owner,
  update_date: '2026-01-01T00:00:00',
});

const tenant = (
  tenant_id: string,
  role: string,
  nickname: string,
  is_active = false,
): ITestTenant => ({
  tenant_id,
  nickname,
  email: `${tenant_id}@example.com`,
  role,
  is_active,
  update_date: '2026-01-01T00:00:00',
});

// The page header keeps the subsection title in its `<h2>` and the workspace it is
// showing on the line under it (`<name> workspace`, or `workspace` alone while the
// workspace record is unknown). The workspace label is what these assertions are
// about: the header must name the WORKSPACE, never the caller's own nickname.
const workspaceLabel = () =>
  screen.getByRole('heading', { level: 2 }).parentElement?.querySelector('p')
    ?.textContent;

// The page normally sits inside the app shell's `TooltipProvider` (the department
// pickers' empty-workspace hint relies on it) and reads `useLocation` to decide
// which workspace section it is showing, so it needs a router even though this
// suite never navigates. Without one React throws
// "useLocation() may be used only in the context of a <Router>" from the page's
// own render.
const renderPage = () =>
  render(
    <MemoryRouter>
      <TooltipProvider>
        <UserSettingTeam />
      </TooltipProvider>
    </MemoryRouter>,
  );

const rowOf = (name: string) => {
  const cell = screen.getByText(name);
  const row = cell.closest('tr');
  if (!row) {
    throw new Error(`no table row contains "${name}"`);
  }
  return row;
};

describe('setting-team page', () => {
  beforeEach(() => {
    mockUser = {
      id: 'user-1',
      nickname: 'Ann Member',
      role: TenantRole.Normal,
    };
    mockTenantInfo = { tenant_id: 'tenant-joined', name: 'Cable Works' };
    mockRoster = [
      member('user-owner', TenantRole.Owner, 'Owner Person', true),
      member('user-2', TenantRole.Admin, 'Admin Person'),
      member('user-1', TenantRole.Normal, 'Ann Member'),
    ];
    mockTenants = [
      tenant('tenant-joined', TenantRole.Normal, 'Joined Workspace', true),
    ];
    mockSetActiveTenant = jest.fn();
    mockUpdateTenantUserRole = jest.fn();
    mockDeleteTenantUser = jest.fn();
  });

  describe('for a NORMAL member', () => {
    it('names the workspace it is showing instead of claiming a personal space', () => {
      renderPage();

      // The name comes from the workspace record (`tenant.name`). The roster
      // list answers each row with the OWNER's user row, so its `nickname` is a
      // person, and the caller's own nickname is never a workspace name.
      expect(workspaceLabel()).toContain('Cable Works');
      expect(workspaceLabel()).not.toContain('Ann Member');
      expect(workspaceLabel()).not.toContain('Owner Person');
    });

    it('names a joined workspace by the workspace, not by its owner', () => {
      // `GET /tenants` answers each row with the owner's profile fields beside
      // the workspace's own `name`; the row names the team, so the owner is not
      // what identifies it.
      mockTenants = [
        {
          ...tenant('tenant-other', TenantRole.Normal, 'Other Owner', false),
          name: 'Ningbo Grid Workspace',
        },
      ];

      renderPage();

      const row = rowOf('Ningbo Grid Workspace');

      expect(row).toHaveTextContent('Ningbo Grid Workspace');
      expect(row).not.toHaveTextContent('Other Owner');
    });

    it('shows the workspace label alone while the workspace record is unknown', () => {
      mockTenantInfo = { tenant_id: 'tenant-joined' };

      renderPage();

      expect(workspaceLabel()).toBe('workspace');
    });

    it('shows the roster read-only, with a role tag on every row', () => {
      renderPage();

      expect(screen.getByText('Admin Person')).toBeInTheDocument();
      expect(
        screen.queryByTestId('member-role-user-2'),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('member-role-user-1'),
      ).not.toBeInTheDocument();
      // Every row, the caller's included, states its role.
      for (const name of ['Owner Person', 'Admin Person', 'Ann Member']) {
        expect(within(rowOf(name)).getByTestId('role-tag')).toBeInTheDocument();
      }
    });

    it('offers no roster management at all', () => {
      renderPage();

      expect(
        screen.queryByRole('button', { name: 'Invite member' }),
      ).not.toBeInTheDocument();
    });
  });

  describe('for an ADMIN', () => {
    beforeEach(() => {
      mockUser = {
        id: 'user-2',
        nickname: 'Admin Person',
        role: TenantRole.Admin,
      };
    });

    it('offers the invite action', () => {
      renderPage();

      expect(
        screen.getByRole('button', { name: 'Invite member' }),
      ).toBeInTheDocument();
    });

    it('offers a role control on the other members but not on its own row', () => {
      renderPage();

      // A NORMAL member can be promoted, so the control is there for them.
      expect(screen.getByTestId('member-role-user-1')).toBeInTheDocument();
      // The caller's own row is refused by the server...
      expect(
        screen.queryByTestId('member-role-user-2'),
      ).not.toBeInTheDocument();
      // ...and the owner's role is never assignable.
      expect(
        screen.queryByTestId('member-role-user-owner'),
      ).not.toBeInTheDocument();
    });

    it('leaves no blank role control on a row whose role is not assignable', () => {
      mockRoster = [
        member('user-owner', TenantRole.Owner, 'Owner Person', true),
        member('user-3', TenantRole.Invite, 'Invited Person'),
      ];

      renderPage();

      // An `invite` role has no entry in the picker, so such a row gets the tag
      // rather than an empty select.
      expect(
        screen.queryByTestId('member-role-user-3'),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByTestId('member-role-user-owner'),
      ).not.toBeInTheDocument();
    });
  });

  describe('joined workspaces', () => {
    beforeEach(() => {
      mockUser = {
        id: 'user-1',
        nickname: 'Ann Member',
        role: TenantRole.Normal,
      };
      mockTenants = [
        tenant('tenant-mine', TenantRole.Owner, 'My Own Workspace', false),
        tenant('tenant-joined', TenantRole.Normal, 'Joined Workspace', true),
        tenant('tenant-other', TenantRole.Admin, 'Other Workspace', false),
        tenant(
          'tenant-pending',
          TenantRole.Invite,
          'Inviting Workspace',
          false,
        ),
      ];
    });

    it('offers a switch on every workspace except the active one', () => {
      renderPage();

      expect(
        within(rowOf('Joined Workspace')).getByText('Current workspace'),
      ).toBeInTheDocument();
      expect(
        within(rowOf('Joined Workspace')).queryByRole('button', {
          name: 'Switch',
        }),
      ).not.toBeInTheDocument();

      expect(
        within(rowOf('Other Workspace')).getByRole('button', {
          name: 'Switch',
        }),
      ).toBeInTheDocument();
      expect(
        within(rowOf('My Own Workspace')).getByRole('button', {
          name: 'Switch',
        }),
      ).toBeInTheDocument();
    });

    it('switches to the workspace whose control was used', () => {
      renderPage();

      fireEvent.click(
        within(rowOf('Other Workspace')).getByRole('button', {
          name: 'Switch',
        }),
      );

      expect(mockSetActiveTenant).toHaveBeenCalledWith('tenant-other');
    });

    it('offers leaving on joined workspaces, including the active one', () => {
      renderPage();

      expect(
        within(rowOf('Joined Workspace')).getByRole('button', { name: 'Quit' }),
      ).toBeInTheDocument();
      expect(
        within(rowOf('Other Workspace')).getByRole('button', { name: 'Quit' }),
      ).toBeInTheDocument();
    });

    it('offers no leaving on a workspace the caller owns', () => {
      renderPage();

      // `DELETE /tenants/<id>/users` refuses the owner, so the control would
      // only ever produce an error.
      expect(
        within(rowOf('My Own Workspace')).queryByRole('button', {
          name: 'Quit',
        }),
      ).not.toBeInTheDocument();
    });

    it('offers accept and decline on a pending invitation instead', () => {
      renderPage();

      expect(
        within(rowOf('Inviting Workspace')).getByText('Accept'),
      ).toBeInTheDocument();
      expect(
        within(rowOf('Inviting Workspace')).getByText('Decline'),
      ).toBeInTheDocument();
      expect(
        within(rowOf('Inviting Workspace')).queryByRole('button', {
          name: 'Quit',
        }),
      ).not.toBeInTheDocument();
    });
  });
});
