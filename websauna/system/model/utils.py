import os
from uuid import UUID
import inspect
from types import ModuleType

from sqlalchemy.ext.declarative import instrument_declarative


def secure_uuid():
    """Create a non-conforming 128-bit random version 4 UUID.

    Random UUID is a RFC 4122 compliant UUID version 4 128-bit number. By default 6 fixed bits, 4 bits for version and 2 bits reserved for other purposes, are fixed. This function behaves like Python's ` uuid4()`` but also randomizes the remaining six bits, generating up to 128 bit randomness.

    This function also sources all bytes from `os.urandom()` to guarantee the randomness and security and does not rely operating system libraries.

    Using ``secure_uuid()`` poses a risk that generated UUIDs are not accepted when communicating with third party system. However, they are observed to be good for URLs and to be stored in PostgreSQL.

    More information

    * http://crypto.stackexchange.com/a/3525/25874

    * https://tools.ietf.org/html/rfc4122
    """
    return UUID(bytes=os.urandom(16), version=4)


def attach_model_to_base(ModelClass:type, Base:type, ignore_reattach:bool=True):
    """Dynamically add a model to chosen SQLAlchemy Base class.

    More flexibility is gained by not inheriting from SQLAlchemy declarative base and instead plugging in models during the configuration time more.

    Directly inheritng from SQLAlchemy Base class has non-undoable side effects. All models automatically pollute SQLAlchemy namespace and may e.g. cause problems with conflicting table names. This also allows @declared_attr to access Pyramid registry.

    Example how to use Pyramid registry in SQLAlchemy's declared attributes::

        class SamplePluggableModel:
            '''Demostrate pluggable model which gets a referred class from Pyramid config.'''
            id = Column(Integer, primary_key=True)

            def __init__(self, **kwargs):
                # Default constructor
                self.__dict__.update(kwargs)

            @declared_attr
            def owner(cls):
                '''Refer to the configured user model.'''
                from websauna.system.user.utils import get_user_class
                config = cls.metadata.pyramid_config
                User = get_user_class(config.registry)
                return relationship(User, backref="referral_programs")

            @declared_attr
            def owner_id(cls):
                '''Refer to user.id column'''
                from websauna.system.user.utils import get_user_class
                config = cls.metadata.pyramid_config
                User = get_user_class(config.registry)
                return Column(Integer, ForeignKey('{}.id'.format(User.__tablename__)))

    Then you need to call in your Initializer::

        from example import models
        from websauna.system.model.meta import Base

        attach_model_to_base(models.SamplePluggableModel, Base)

    :param ModelClass: SQLAlchemy model class

    :param Base: SQLAlchemy declarative Base for which model should belong to

    :param ignore_reattach: Do nothing if ``ModelClass`` is already attached to base. Base registry is effectively global. ``attach_model_to_base()`` may be called several times within the same process during unit tests runs. Complain only if we try to attach a different base.
    """

    if ignore_reattach:
         if '_decl_class_registry' in ModelClass.__dict__:
            assert ModelClass._decl_class_registry == Base._decl_class_registry, "Tried to attach to a different Base"
            return

    instrument_declarative(ModelClass, Base._decl_class_registry, Base.metadata)


def attach_models_to_base_from_module(mod:ModuleType, Base:type):
    """Attach all models in a Python module to SQLAlchemy base class.

    All models must declare ``__tablename__`` property.
    """

    for key in dir(mod):
        value = getattr(mod, key)
        if inspect.isclass(value):
            if hasattr(value, "__tablename__"):
                attach_model_to_base(value, Base)