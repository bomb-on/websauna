"""Map SQLAlchemy columns and other class attributes to Colander schema.

Also encapsulate :term:`colanderalchemy` so that we don't need to directly expose it in the case we want to get rid of it later.
"""
import logging

import colander
import deform
import sqlalchemy

from abc import ABC, abstractmethod
from sqlalchemy import Column
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID, JSONB, INET
from sqlalchemy.orm import RelationshipProperty, Mapper
from sqlalchemy.sql.type_api import TypeEngine
from websauna.system.crud import Resource
from websauna.system.form.colander import PropertyAwareSQLAlchemySchemaNode, TypeOverridesHandling
from websauna.system.form.sqlalchemy import get_uuid_vocabulary_for_model, UUIDModelSet, UUIDForeignKeyValue
from websauna.system.form.widgets import FriendlyUUIDWidget
from websauna.system.http import Request

from websauna.compat.typing import List
from websauna.compat.typing import Tuple
from websauna.compat.typing import Optional

from . import fields
from .editmode import EditMode

logger = logging.getLogger(__name__)


class ColumnToFieldMapper(ABC):
    """A helper class to map a SQLAlchemy model to Colander/Deform form."""

    @abstractmethod
    def map(self, mode:EditMode, request:Request, context:Resource, model:type, includes:List) -> colander.SchemaNode:
        """Map a model to a Colander form schema.

        :param mode: IS this add, edit or show form. For example, some relationship fields do not make sense on add form.

        :param context: Resource with ``get_object()`` to get the actual SQLAlchemy object

        :param model: SQLAlchemy model class

        :param includes: List of [column name | SchemaNode] we need to map

        :return: colander.SchemaNode which presents the automatically generated form
        """


class DefaultSQLAlchemyFieldMapper(ColumnToFieldMapper):
    """The default SQLAlchemy to form field and widget mapping implementation.

    We support

    * The default colanderalchemy mappings

    * UUID

    * JSONProperty declarations

    * IP addresses (INET)

    * ForeignKey references where it holds a reference to one another SQLAlchemy object

    See :py:class:`colanderalchemy.schema.SQLAlchemySchemaNode` for more information.
    """

    def map_standard_relationship(self, mode, request, node, model, name, rel) -> colander.SchemaNode:
        """Build a widget for choosing a relationship with target.

        The relationship must be foreign_key and the remote must offer ``uuid`` attribute which we use as a vocabulary key..
        """

        remote_model = rel.argument()

        if type(remote_model) not in (sqlalchemy.ext.declarative.api.DeclarativeMeta, type):
            # We were passed an instance of a model instead of model class itself
            remote_model = remote_model.__class__

        # Get first column of the set
        for column in rel.local_columns:
            break

        # For now, we automatically deal with this only if the model provides uuid
        if hasattr(remote_model, "uuid"):
            dbsession = request.dbsession
            # TODO: We probably need a mechanism for system wide empty default label

            required = not column.nullable

            if mode in (EditMode.add, EditMode.edit):
                default_choice = "--- Choose one ---"
            else:
                default_choice = "(not set)"

            if required:
                missing = colander.required
            else:
                missing = None

            vocabulary = get_uuid_vocabulary_for_model(dbsession, remote_model, default_choice=default_choice)

            if rel.uselist:
                # Show out all relationships
                if mode == EditMode.show:
                    return colander.SchemaNode(UUIDModelSet(remote_model), name=name, missing=missing, widget=deform.widget.CheckboxChoiceWidget(values=vocabulary))
            else:
                # Select from a single relationship
                return colander.SchemaNode(UUIDForeignKeyValue(remote_model), name=name, missing=missing, widget=deform.widget.SelectWidget(values=vocabulary))

        return TypeOverridesHandling.drop

    def map_relationship(self, mode: EditMode, request: Request, node: colander.SchemaNode, model: type, name: str, rel: RelationshipProperty, mapper: Mapper):

        # Ok this is something we can handle, a single reference to another
        return self.map_standard_relationship(mode, request, node, model, name, rel)

    def map_column(self, mode:EditMode, request:Request, node:colander.SchemaNode, model:type, name:str, column:Column, column_type:TypeEngine) -> Tuple[colander.SchemaType, dict]:

        logger.debug("Mapping field %s, mode %s, node %s, column %s", name, mode, node, column)

        # Never add primary keys
        # NOTE: TODO: We need to preserve ids because of nesting mechanism and groupedit widget wants it id
        if column.primary_key:
            # TODO: Looks like column.autoincrement is set True by default, so we cannot use it here
            if mode in (EditMode.edit, EditMode.add):
                return TypeOverridesHandling.drop, {}

        if column.foreign_keys:

            # Handled by relationship mapper
            return TypeOverridesHandling.drop, {}

        elif isinstance(column_type, PostgreSQLUUID):

            # UUID's cannot be edited
            if mode in (EditMode.add, EditMode.edit):
                return TypeOverridesHandling.drop, {}

            # But let's show them
            return fields.UUID(), dict(missing=colander.drop, widget=FriendlyUUIDWidget(readonly=True))
        elif isinstance(column_type, JSONB):

            # Can't edit JSON
            if mode in (EditMode.add, EditMode.edit):
                return TypeOverridesHandling.drop, {}

            return colander.String(), {}
        elif isinstance(column_type, INET):
            return colander.String(), {}
        else:
            # Default mapping / unknown, let the parent handle
            return TypeOverridesHandling.unknown, {}

    def map(self, mode: EditMode, request: Request, context: Optional[Resource], model: type, includes: List, nested=None) -> colander.SchemaNode:
        """
        :param mode: What kind of form is this - show, add, edit
        :param request: HTTP request
        :param context: Current traversing context or None
        :param model: The SQLAlchemy model class for which we generate schema
        :param includes: List of column, relationship and property names or ``colander.SchemaNode(name=name) instances to be included on the form.
        :param nested: Legacy. Going away.
        """

        def _map_column(node, name, column, column_type):
            return self.map_column(mode, request, node, model, name, column, column_type)

        def _map_relationship(node: colander.SchemaNode, name: str, prop: RelationshipProperty, mapper: Mapper):
            return self.map_relationship(mode, request, node, model, name, prop, mapper)

        # TODO: We need to get rid of nested
        # Don't try to pull in relatinoships on add form
        nested = True

        schema = PropertyAwareSQLAlchemySchemaNode(model, includes=includes, type_overrides=_map_column, relationship_overrides=_map_relationship, automatic_relationships=True, nested=nested)
        return schema


