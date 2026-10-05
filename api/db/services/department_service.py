#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
from api.db.db_models import DB, Department, UserTenant
from api.db.services.common_service import CommonService
from common.constants import StatusEnum


class DepartmentService(CommonService):
    """Departments inside a tenant.

    A department is scoped to one tenant, so every lookup takes the tenant id as
    well as the department id: an id from another workspace must never resolve.
    """

    model = Department

    @classmethod
    @DB.connection_context()
    def list_by_tenant_id(cls, tenant_id):
        """Every department of the tenant, ordered by name.

        Flat: `parent_id` is returned so a caller may build a tree, but nothing
        here assumes one.
        """
        return list(cls.model.select().where((cls.model.tenant_id == tenant_id) & (cls.model.status == StatusEnum.VALID.value)).order_by(cls.model.name).dicts())

    @classmethod
    @DB.connection_context()
    def get_by_tenant_and_id(cls, tenant_id, department_id):
        return cls.model.select().where((cls.model.tenant_id == tenant_id) & (cls.model.id == department_id) & (cls.model.status == StatusEnum.VALID.value)).first()

    @classmethod
    @DB.connection_context()
    def find_by_tenant_and_name(cls, tenant_id, name):
        return cls.model.select().where((cls.model.tenant_id == tenant_id) & (cls.model.name == name) & (cls.model.status == StatusEnum.VALID.value)).first()

    @classmethod
    @DB.connection_context()
    def count_members(cls, tenant_id, department_id):
        """How many active memberships point at the department."""
        return UserTenant.select().where((UserTenant.tenant_id == tenant_id) & (UserTenant.department_id == department_id) & (UserTenant.status == StatusEnum.VALID.value)).count()
