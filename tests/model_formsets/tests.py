import datetime
import re
from datetime import date
from decimal import Decimal

from django import forms
from django.core.exceptions import ImproperlyConfigured
from django.db import models
from django.forms.formsets import formset_factory
from django.forms.models import (
    BaseInlineFormSet,
    BaseModelFormSet,
    InlineFormSet,
    ModelForm,
    ModelFormSet,
    _get_foreign_key,
    inlineformset_factory,
    modelformset_factory,
)
from django.forms.renderers import DjangoTemplates
from django.http import QueryDict
from django.test import TestCase, skipUnlessDBFeature

from .models import (
    AlternateBook,
    Author,
    AuthorMeeting,
    BetterAuthor,
    Book,
    BookWithCustomPK,
    BookWithOptionalAltEditor,
    ClassyMexicanRestaurant,
    CustomPrimaryKey,
    Location,
    Membership,
    MexicanRestaurant,
    Owner,
    OwnerProfile,
    Person,
    Place,
    Player,
    Poem,
    Poet,
    Post,
    Price,
    Product,
    Repository,
    Restaurant,
    Revision,
    Team,
)


class PoetForm(forms.ModelForm):
    def save(self, commit=True):
        # change the name to "Vladimir Mayakovsky" just to be a jerk.
        author = super().save(commit=False)
        author.name = "Vladimir Mayakovsky"
        if commit:
            author.save()
        return author


class PostForm1(forms.ModelForm):
    class Meta:
        model = Post
        fields = ("title", "posted")


class PostForm2(forms.ModelForm):
    class Meta:
        model = Post
        exclude = ("subtitle",)


class BaseAuthorFormSet(BaseModelFormSet):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queryset = Author.objects.filter(name__startswith="Charles")


class PoemFormSave(forms.ModelForm):
    def save(self, commit=True):
        # change the name to "Brooklyn Bridge" just to be a jerk.
        poem = super().save(commit=False)
        poem.name = "Brooklyn Bridge"
        if commit:
            poem.save()
        return poem


class PoemFormSave2(forms.ModelForm):
    def save(self, commit=True):
        poem = super().save(commit=False)
        poem.name = "%s by %s" % (poem.name, poem.poet.name)
        if commit:
            poem.save()
        return poem


class PoemFormField(ModelForm):
    class Meta:
        model = Poem
        fields = ("name",)


class SimpleArrayField(forms.CharField):
    """A proxy for django.contrib.postgres.forms.SimpleArrayField."""

    def to_python(self, value):
        value = super().to_python(value)
        return value.split(",") if value else []


class BookFormArrayField(forms.ModelForm):
    title = SimpleArrayField()

    class Meta:
        model = Book
        fields = ("title",)


class CustomInlineFormSet(BaseInlineFormSet):
    """A custom base inline formset."""

    def clean(self):
        """Clean method."""
        super().clean()
        for form in self.forms:
            lowered_name = form.cleaned_data["name"].lower()
            form.cleaned_data["name"] = lowered_name
            form.instance.name = lowered_name


class DeletionTestsMixin:
    """A mixin to test deletion in declarative and factory modelformsets."""

    def test_deletion(self):
        poet = Poet.objects.create(name="test")
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "0",
            "form-0-id": str(poet.pk),
            "form-0-name": "test",
            "form-0-DELETE": "on",
        }
        formset = self.model_formset(data, queryset=Poet.objects.all())
        formset.save(commit=False)
        self.assertEqual(Poet.objects.count(), 1)

        formset.save()
        self.assertTrue(formset.is_valid())
        self.assertEqual(Poet.objects.count(), 0)

    def test_add_form_deletion_when_invalid(self):
        """
        Make sure that an add form that is filled out, but marked for deletion
        doesn't cause validation errors.
        """
        poet = Poet.objects.create(name="test")
        # One existing untouched and two new unvalid forms
        data = {
            "form-TOTAL_FORMS": "3",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "0",
            "form-0-id": str(poet.id),
            "form-0-name": "test",
            "form-1-id": "",
            "form-1-name": "x" * 1000,  # Too long
            "form-2-id": str(poet.id),  # Violate unique constraint
            "form-2-name": "test2",
        }
        formset = self.model_formset(data, queryset=Poet.objects.all())
        # Make sure this form doesn't pass validation.
        self.assertIs(formset.is_valid(), False)
        self.assertEqual(Poet.objects.count(), 1)

        # Then make sure that it *does* pass validation and delete the object,
        # even though the data in new forms aren't actually valid.
        data["form-0-DELETE"] = "on"
        data["form-1-DELETE"] = "on"
        data["form-2-DELETE"] = "on"
        formset = self.model_formset(data, queryset=Poet.objects.all())
        self.assertIs(formset.is_valid(), True)
        formset.save()
        self.assertEqual(Poet.objects.count(), 0)

    def test_change_form_deletion_when_invalid(self):
        """
        Make sure that a change form that is filled out, but marked for deletion
        doesn't cause validation errors.
        """
        poet = Poet.objects.create(name="test")
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "0",
            "form-0-id": str(poet.id),
            "form-0-name": "x" * 1000,
        }
        formset = self.model_formset(data, queryset=Poet.objects.all())
        # Make sure this form doesn't pass validation.
        self.assertIs(formset.is_valid(), False)
        self.assertEqual(Poet.objects.count(), 1)

        # Then make sure that it *does* pass validation and delete the object,
        # even though the data isn't actually valid.
        data["form-0-DELETE"] = "on"
        formset = self.model_formset(data, queryset=Poet.objects.all())
        self.assertIs(formset.is_valid(), True)
        formset.save()
        self.assertEqual(Poet.objects.count(), 0)

    def test_outdated_deletion(self):
        poet = Poet.objects.create(name="test")
        poem = Poem.objects.create(name="Brevity is the soul of wit", poet=poet)

        # Simulate deletion of an object that doesn't exist in the database
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "2",
            "form-0-id": str(poem.pk),
            "form-0-name": "foo",
            "form-1-id": str(poem.pk + 1),  # doesn't exist
            "form-1-name": "bar",
            "form-1-DELETE": "on",
        }
        formset = self.inline_formset(data, instance=poet, prefix="form")

        # The formset is valid even though poem.pk + 1 doesn't exist,
        # because it's marked for deletion anyway
        self.assertTrue(formset.is_valid())

        formset.save()

        # Make sure the save went through correctly
        self.assertEqual(Poem.objects.get(pk=poem.pk).name, "foo")
        self.assertEqual(poet.poem_set.count(), 1)
        self.assertFalse(Poem.objects.filter(pk=poem.pk + 1).exists())


class FactoryFormSetDeletionTests(TestCase, DeletionTestsMixin):
    """A set of tests to test deletion of modelformsets and inlineformset.

    Created with factories.
    """

    # modelformsets
    model_formset = modelformset_factory(Poet, fields="__all__", can_delete=True)
    # inlineformsets
    inline_formset = inlineformset_factory(
        Poet, Poem, fields="__all__", can_delete=True
    )


class DeclarativeFormSetDeletionTests(TestCase, DeletionTestsMixin):
    """A set of tests to test deletion of modelformsets and inlineformset.

    Created with declarative syntax.
    """

    class DeclarativePoetFormSet(ModelFormSet):
        model = Poet
        fields = "__all__"
        can_delete = True

    class DeclarativePoetInlineSet(InlineFormSet):
        """A declarative poet inlineformset."""

        parent_model = Poet
        model = Poem
        fields = "__all__"
        can_delete = True

    # modelformsets
    model_formset = DeclarativePoetFormSet
    # inlineformsets
    inline_formset = DeclarativePoetInlineSet


class ModelFormsetTestMixin:
    """A mixin to test declarative and factory model_formsets."""

    def test_simple_save(self):
        qs = Author.objects.all()
        formset = self.author_formset_extra_3(queryset=qs)
        self.assertEqual(len(formset.forms), 3)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_form-0-name">Name:</label>'
            '<input id="id_form-0-name" type="text" name="form-0-name" maxlength="100">'
            '<input type="hidden" name="form-0-id" id="id_form-0-id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_form-1-name">Name:</label>'
            '<input id="id_form-1-name" type="text" name="form-1-name" maxlength="100">'
            '<input type="hidden" name="form-1-id" id="id_form-1-id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_form-2-name">Name:</label>'
            '<input id="id_form-2-name" type="text" name="form-2-name" maxlength="100">'
            '<input type="hidden" name="form-2-id" id="id_form-2-id"></p>',
        )

        data = {
            "form-TOTAL_FORMS": "3",  # the number of forms rendered
            "form-INITIAL_FORMS": "0",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-name": "Charles Baudelaire",
            "form-1-name": "Arthur Rimbaud",
            "form-2-name": "",
        }

        formset = self.author_formset_extra_3(data=data, queryset=qs)
        self.assertTrue(formset.is_valid())

        saved = formset.save()
        self.assertEqual(len(saved), 2)
        author1, author2 = saved
        self.assertEqual(author1, Author.objects.get(name="Charles Baudelaire"))
        self.assertEqual(author2, Author.objects.get(name="Arthur Rimbaud"))

        authors = list(Author.objects.order_by("name"))
        self.assertEqual(authors, [author2, author1])

        # Gah! We forgot Paul Verlaine. Let's create a formset to edit the
        # existing authors with an extra form to add him. We *could* pass in a
        # queryset to restrict the Author objects we edit, but in this case
        # we'll use it to display them in alphabetical order by name.

        qs = Author.objects.order_by("name")
        formset = self.author_formset_delete_false(queryset=qs)
        self.assertEqual(len(formset.forms), 3)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_form-0-name">Name:</label>'
            '<input id="id_form-0-name" type="text" name="form-0-name" '
            'value="Arthur Rimbaud" maxlength="100">'
            '<input type="hidden" name="form-0-id" value="%d" id="id_form-0-id"></p>'
            % author2.id,
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_form-1-name">Name:</label>'
            '<input id="id_form-1-name" type="text" name="form-1-name" '
            'value="Charles Baudelaire" maxlength="100">'
            '<input type="hidden" name="form-1-id" value="%d" id="id_form-1-id"></p>'
            % author1.id,
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_form-2-name">Name:</label>'
            '<input id="id_form-2-name" type="text" name="form-2-name" maxlength="100">'
            '<input type="hidden" name="form-2-id" id="id_form-2-id"></p>',
        )

        data = {
            "form-TOTAL_FORMS": "3",  # the number of forms rendered
            "form-INITIAL_FORMS": "2",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-id": str(author2.id),
            "form-0-name": "Arthur Rimbaud",
            "form-1-id": str(author1.id),
            "form-1-name": "Charles Baudelaire",
            "form-2-name": "Paul Verlaine",
        }

        formset = self.author_formset_delete_false(data=data, queryset=qs)
        self.assertTrue(formset.is_valid())

        # Only changed or new objects are returned from formset.save()
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        author3 = saved[0]
        self.assertEqual(author3, Author.objects.get(name="Paul Verlaine"))

        authors = list(Author.objects.order_by("name"))
        self.assertEqual(authors, [author2, author1, author3])

        # This probably shouldn't happen, but it will. If an add form was
        # marked for deletion, make sure we don't save that form.

        qs = Author.objects.order_by("name")
        formset = self.author_formset_delete_true(queryset=qs)
        self.assertEqual(len(formset.forms), 4)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_form-0-name">Name:</label>'
            '<input id="id_form-0-name" type="text" name="form-0-name" '
            'value="Arthur Rimbaud" maxlength="100"></p>'
            '<p><label for="id_form-0-DELETE">Delete:</label>'
            '<input type="checkbox" name="form-0-DELETE" id="id_form-0-DELETE">'
            '<input type="hidden" name="form-0-id" value="%d" id="id_form-0-id"></p>'
            % author2.id,
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_form-1-name">Name:</label>'
            '<input id="id_form-1-name" type="text" name="form-1-name" '
            'value="Charles Baudelaire" maxlength="100"></p>'
            '<p><label for="id_form-1-DELETE">Delete:</label>'
            '<input type="checkbox" name="form-1-DELETE" id="id_form-1-DELETE">'
            '<input type="hidden" name="form-1-id" value="%d" id="id_form-1-id"></p>'
            % author1.id,
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_form-2-name">Name:</label>'
            '<input id="id_form-2-name" type="text" name="form-2-name" '
            'value="Paul Verlaine" maxlength="100"></p>'
            '<p><label for="id_form-2-DELETE">Delete:</label>'
            '<input type="checkbox" name="form-2-DELETE" id="id_form-2-DELETE">'
            '<input type="hidden" name="form-2-id" value="%d" id="id_form-2-id"></p>'
            % author3.id,
        )
        self.assertHTMLEqual(
            formset.forms[3].as_p(),
            '<p><label for="id_form-3-name">Name:</label>'
            '<input id="id_form-3-name" type="text" name="form-3-name" maxlength="100">'
            '</p><p><label for="id_form-3-DELETE">Delete:</label>'
            '<input type="checkbox" name="form-3-DELETE" id="id_form-3-DELETE">'
            '<input type="hidden" name="form-3-id" id="id_form-3-id"></p>',
        )

        data = {
            "form-TOTAL_FORMS": "4",  # the number of forms rendered
            "form-INITIAL_FORMS": "3",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-id": str(author2.id),
            "form-0-name": "Arthur Rimbaud",
            "form-1-id": str(author1.id),
            "form-1-name": "Charles Baudelaire",
            "form-2-id": str(author3.id),
            "form-2-name": "Paul Verlaine",
            "form-3-name": "Walt Whitman",
            "form-3-DELETE": "on",
        }

        formset = self.author_formset_delete_true(data=data, queryset=qs)
        self.assertTrue(formset.is_valid())

        # No objects were changed or saved so nothing will come back.

        self.assertEqual(formset.save(), [])

        authors = list(Author.objects.order_by("name"))
        self.assertEqual(authors, [author2, author1, author3])

        # Let's edit a record to ensure save only returns that one record.

        data = {
            "form-TOTAL_FORMS": "4",  # the number of forms rendered
            "form-INITIAL_FORMS": "3",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-id": str(author2.id),
            "form-0-name": "Walt Whitman",
            "form-1-id": str(author1.id),
            "form-1-name": "Charles Baudelaire",
            "form-2-id": str(author3.id),
            "form-2-name": "Paul Verlaine",
            "form-3-name": "",
            "form-3-DELETE": "",
        }

        formset = self.author_formset_delete_true(data=data, queryset=qs)
        self.assertTrue(formset.is_valid())

        # One record has changed.

        saved = formset.save()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0], Author.objects.get(name="Walt Whitman"))

    def test_commit_false(self):
        # Test the behavior of commit=False and save_m2m

        author1 = Author.objects.create(name="Charles Baudelaire")
        author2 = Author.objects.create(name="Paul Verlaine")
        author3 = Author.objects.create(name="Walt Whitman")

        meeting = AuthorMeeting.objects.create(created=date.today())
        meeting.authors.set(Author.objects.all())

        # create an Author instance to add to the meeting.

        author4 = Author.objects.create(name="John Steinbeck")
        data = {
            "form-TOTAL_FORMS": "2",  # the number of forms rendered
            "form-INITIAL_FORMS": "1",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-id": str(meeting.id),
            "form-0-name": "2nd Tuesday of the Week Meeting",
            "form-0-authors": [author2.id, author1.id, author3.id, author4.id],
            "form-1-name": "",
            "form-1-authors": "",
            "form-1-DELETE": "",
        }
        formset = self.author_meeting_delete_true(
            data=data, queryset=AuthorMeeting.objects.all()
        )
        self.assertTrue(formset.is_valid())

        instances = formset.save(commit=False)
        for instance in instances:
            instance.created = date.today()
            instance.save()
        formset.save_m2m()
        self.assertSequenceEqual(
            instances[0].authors.all(),
            [author1, author4, author2, author3],
        )

    def test_max_num(self):
        # Test the behavior of max_num with model formsets. It should allow
        # all existing related objects/inlines for a given object to be
        # displayed, but not allow the creation of new inlines beyond max_num.

        a1 = Author.objects.create(name="Charles Baudelaire")
        a2 = Author.objects.create(name="Paul Verlaine")
        a3 = Author.objects.create(name="Walt Whitman")

        qs = Author.objects.order_by("name")

        formset = self.author_formset_no_max(queryset=qs)
        self.assertEqual(len(formset.forms), 6)
        self.assertEqual(len(formset.extra_forms), 3)

        formset = self.author_formset_max_greater(queryset=qs)
        self.assertEqual(len(formset.forms), 4)
        self.assertEqual(len(formset.extra_forms), 1)

        formset = self.author_formset_max_0_extra(queryset=qs)
        self.assertEqual(len(formset.forms), 3)
        self.assertEqual(len(formset.extra_forms), 0)

        formset = self.author_formset_max_none(queryset=qs)
        self.assertSequenceEqual(formset.get_queryset(), [a1, a2, a3])

        formset = self.author_formset_max_0(queryset=qs)
        self.assertSequenceEqual(formset.get_queryset(), [a1, a2, a3])

        formset = self.author_formset_max(queryset=qs)
        self.assertSequenceEqual(formset.get_queryset(), [a1, a2, a3])

    def test_min_num(self):
        # Test the behavior of min_num with model formsets. It should be
        # added to extra.
        qs = Author.objects.none()

        formset = self.author_formset_extra_0(queryset=qs)
        self.assertEqual(len(formset.forms), 0)

        formset = self.author_formset_min_greater(queryset=qs)
        self.assertEqual(len(formset.forms), 1)

        formset = self.author_formset_same_min_extra(queryset=qs)
        self.assertEqual(len(formset.forms), 2)

    def test_min_num_with_existing(self):
        # Test the behavior of min_num with existing objects.
        Author.objects.create(name="Charles Baudelaire")
        qs = Author.objects.all()

        formset = self.author_formset_min_greater(queryset=qs)
        self.assertEqual(len(formset.forms), 1)

    def test_custom_save_method(self):
        data = {
            "form-TOTAL_FORMS": "3",  # the number of forms rendered
            "form-INITIAL_FORMS": "0",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-name": "Walt Whitman",
            "form-1-name": "Charles Baudelaire",
            "form-2-name": "",
        }

        qs = Poet.objects.all()
        formset = self.poet_formset_model_and_form(data=data, queryset=qs)
        self.assertTrue(formset.is_valid())

        poets = formset.save()
        self.assertEqual(len(poets), 2)
        poet1, poet2 = poets
        self.assertEqual(poet1.name, "Vladimir Mayakovsky")
        self.assertEqual(poet2.name, "Vladimir Mayakovsky")

    def test_custom_form(self):
        """
        model_formset_factory() respects fields and exclude parameters of a
        custom form.
        """
        formset = self.post_formset_form1()
        self.assertNotIn("subtitle", formset.forms[0].fields)

        formset = self.post_formset_form2()
        self.assertNotIn("subtitle", formset.forms[0].fields)

    def test_custom_queryset_init(self):
        """A queryset can be overridden in the formset's __init__() method."""
        Author.objects.create(name="Charles Baudelaire")
        Author.objects.create(name="Paul Verlaine")

        formset = self.author_formset_custom_base()
        self.assertEqual(len(formset.get_queryset()), 1)

    def test_model_inheritance(self):
        formset = self.better_author_formset()
        self.assertEqual(len(formset.forms), 1)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_form-0-name">Name:</label>'
            '<input id="id_form-0-name" type="text" name="form-0-name" maxlength="100">'
            '</p><p><label for="id_form-0-write_speed">Write speed:</label>'
            '<input type="number" name="form-0-write_speed" id="id_form-0-write_speed">'
            '<input type="hidden" name="form-0-author_ptr" id="id_form-0-author_ptr">'
            "</p>",
        )

        data = {
            "form-TOTAL_FORMS": "1",  # the number of forms rendered
            "form-INITIAL_FORMS": "0",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-author_ptr": "",
            "form-0-name": "Ernest Hemingway",
            "form-0-write_speed": "10",
        }

        formset = self.better_author_formset(data)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (author1,) = saved
        self.assertEqual(author1, BetterAuthor.objects.get(name="Ernest Hemingway"))
        hemingway_id = BetterAuthor.objects.get(name="Ernest Hemingway").pk

        formset = self.better_author_formset()
        self.assertEqual(len(formset.forms), 2)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_form-0-name">Name:</label>'
            '<input id="id_form-0-name" type="text" name="form-0-name" '
            'value="Ernest Hemingway" maxlength="100"></p>'
            '<p><label for="id_form-0-write_speed">Write speed:</label>'
            '<input type="number" name="form-0-write_speed" value="10" '
            'id="id_form-0-write_speed">'
            '<input type="hidden" name="form-0-author_ptr" value="%d" '
            'id="id_form-0-author_ptr"></p>' % hemingway_id,
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_form-1-name">Name:</label>'
            '<input id="id_form-1-name" type="text" name="form-1-name" maxlength="100">'
            '</p><p><label for="id_form-1-write_speed">Write speed:</label>'
            '<input type="number" name="form-1-write_speed" id="id_form-1-write_speed">'
            '<input type="hidden" name="form-1-author_ptr" id="id_form-1-author_ptr">'
            "</p>",
        )

        data = {
            "form-TOTAL_FORMS": "2",  # the number of forms rendered
            "form-INITIAL_FORMS": "1",  # the number of forms with initial data
            "form-MAX_NUM_FORMS": "",  # the max number of forms
            "form-0-author_ptr": hemingway_id,
            "form-0-name": "Ernest Hemingway",
            "form-0-write_speed": "10",
            "form-1-author_ptr": "",
            "form-1-name": "",
            "form-1-write_speed": "",
        }

        formset = self.better_author_formset(data)
        self.assertTrue(formset.is_valid())
        self.assertEqual(formset.save(), [])

    def test_inline_formsets(self):
        # We can also create a formset that is tied to a parent model. This is
        # how the admin system's edit inline functionality works.

        author = Author.objects.create(name="Charles Baudelaire")

        formset = self.book_inlineformset_extra_3(instance=author)
        self.assertEqual(len(formset.forms), 3)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_book_set-0-title">Title:</label>'
            '<input id="id_book_set-0-title" type="text" name="book_set-0-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-0-author" value="%d" '
            'id="id_book_set-0-author">'
            '<input type="hidden" name="book_set-0-id" id="id_book_set-0-id">'
            "</p>" % author.id,
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_book_set-1-title">Title:</label>'
            '<input id="id_book_set-1-title" type="text" name="book_set-1-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-1-author" value="%d" '
            'id="id_book_set-1-author">'
            '<input type="hidden" name="book_set-1-id" id="id_book_set-1-id"></p>'
            % author.id,
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_book_set-2-title">Title:</label>'
            '<input id="id_book_set-2-title" type="text" name="book_set-2-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-2-author" value="%d" '
            'id="id_book_set-2-author">'
            '<input type="hidden" name="book_set-2-id" id="id_book_set-2-id"></p>'
            % author.id,
        )

        data = {
            "book_set-TOTAL_FORMS": "3",  # the number of forms rendered
            "book_set-INITIAL_FORMS": "0",  # the number of forms with initial data
            "book_set-MAX_NUM_FORMS": "",  # the max number of forms
            "book_set-0-title": "Les Fleurs du Mal",
            "book_set-1-title": "",
            "book_set-2-title": "",
        }

        formset = self.book_inlineformset_extra_3(data, instance=author)
        self.assertTrue(formset.is_valid())

        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (book1,) = saved
        self.assertEqual(book1, Book.objects.get(title="Les Fleurs du Mal"))
        self.assertSequenceEqual(author.book_set.all(), [book1])

        # Now that we've added a book to Charles Baudelaire, let's try adding
        # another one. This time though, an edit form will be available for
        # every existing book.

        author = Author.objects.get(name="Charles Baudelaire")

        formset = self.book_inlineformset_extra_2(instance=author)
        self.assertEqual(len(formset.forms), 3)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_book_set-0-title">Title:</label>'
            '<input id="id_book_set-0-title" type="text" name="book_set-0-title" '
            'value="Les Fleurs du Mal" maxlength="100">'
            '<input type="hidden" name="book_set-0-author" value="%d" '
            'id="id_book_set-0-author">'
            '<input type="hidden" name="book_set-0-id" value="%d" '
            'id="id_book_set-0-id"></p>'
            % (
                author.id,
                book1.id,
            ),
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_book_set-1-title">Title:</label>'
            '<input id="id_book_set-1-title" type="text" name="book_set-1-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-1-author" value="%d" '
            'id="id_book_set-1-author">'
            '<input type="hidden" name="book_set-1-id" id="id_book_set-1-id"></p>'
            % author.id,
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_book_set-2-title">Title:</label>'
            '<input id="id_book_set-2-title" type="text" name="book_set-2-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-2-author" value="%d" '
            'id="id_book_set-2-author">'
            '<input type="hidden" name="book_set-2-id" id="id_book_set-2-id"></p>'
            % author.id,
        )

        data = {
            "book_set-TOTAL_FORMS": "3",  # the number of forms rendered
            "book_set-INITIAL_FORMS": "1",  # the number of forms with initial data
            "book_set-MAX_NUM_FORMS": "",  # the max number of forms
            "book_set-0-id": str(book1.id),
            "book_set-0-title": "Les Fleurs du Mal",
            "book_set-1-title": "Les Paradis Artificiels",
            "book_set-2-title": "",
        }

        formset = self.book_inlineformset_extra_2(data, instance=author)
        self.assertTrue(formset.is_valid())

        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (book2,) = saved
        self.assertEqual(book2, Book.objects.get(title="Les Paradis Artificiels"))

        # As you can see, 'Les Paradis Artificiels' is now a book belonging to
        # Charles Baudelaire.
        self.assertSequenceEqual(author.book_set.order_by("title"), [book1, book2])

    def test_inline_formsets_save_as_new(self):
        # The save_as_new parameter lets you re-associate the data to a new
        # instance.  This is used in the admin for save_as functionality.
        Author.objects.create(name="Charles Baudelaire")

        # An immutable QueryDict simulates request.POST.
        data = QueryDict(mutable=True)
        data.update(
            {
                "book_set-TOTAL_FORMS": "3",  # the number of forms rendered
                "book_set-INITIAL_FORMS": "2",  # the number of forms with initial data
                "book_set-MAX_NUM_FORMS": "",  # the max number of forms
                "book_set-0-id": "1",
                "book_set-0-title": "Les Fleurs du Mal",
                "book_set-1-id": "2",
                "book_set-1-title": "Les Paradis Artificiels",
                "book_set-2-title": "",
            }
        )
        data._mutable = False

        formset = self.book_inlineformset_extra_2(
            data, instance=Author(), save_as_new=True
        )
        self.assertTrue(formset.is_valid())
        self.assertIs(data._mutable, False)

        new_author = Author.objects.create(name="Charles Baudelaire")
        formset = self.book_inlineformset_extra_2(
            data, instance=new_author, save_as_new=True
        )
        saved = formset.save()
        self.assertEqual(len(saved), 2)
        book1, book2 = saved
        self.assertEqual(book1.title, "Les Fleurs du Mal")
        self.assertEqual(book2.title, "Les Paradis Artificiels")

        # Test using a custom prefix on an inline formset.

        formset = self.book_inlineformset_extra_2(prefix="test")
        self.assertEqual(len(formset.forms), 2)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_test-0-title">Title:</label>'
            '<input id="id_test-0-title" type="text" name="test-0-title" '
            'maxlength="100">'
            '<input type="hidden" name="test-0-author" id="id_test-0-author">'
            '<input type="hidden" name="test-0-id" id="id_test-0-id"></p>',
        )

        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_test-1-title">Title:</label>'
            '<input id="id_test-1-title" type="text" name="test-1-title" '
            'maxlength="100">'
            '<input type="hidden" name="test-1-author" id="id_test-1-author">'
            '<input type="hidden" name="test-1-id" id="id_test-1-id"></p>',
        )

    def test_inline_formsets_with_custom_pk(self):
        # Test inline formsets where the inline-edited object has a custom
        # primary key that is not the fk to the parent object.
        self.maxDiff = 1024

        author = Author.objects.create(pk=1, name="Charles Baudelaire")

        formset = self.book_custom_pk_inlineformset(instance=author)
        self.assertEqual(len(formset.forms), 1)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_bookwithcustompk_set-0-my_pk">My pk:</label>'
            '<input id="id_bookwithcustompk_set-0-my_pk" type="number" '
            'name="bookwithcustompk_set-0-my_pk" step="1"></p>'
            '<p><label for="id_bookwithcustompk_set-0-title">Title:</label>'
            '<input id="id_bookwithcustompk_set-0-title" type="text" '
            'name="bookwithcustompk_set-0-title" maxlength="100">'
            '<input type="hidden" name="bookwithcustompk_set-0-author" '
            'value="1" id="id_bookwithcustompk_set-0-author"></p>',
        )

        data = {
            # The number of forms rendered.
            "bookwithcustompk_set-TOTAL_FORMS": "1",
            # The number of forms with initial data.
            "bookwithcustompk_set-INITIAL_FORMS": "0",
            # The max number of forms.
            "bookwithcustompk_set-MAX_NUM_FORMS": "",
            "bookwithcustompk_set-0-my_pk": "77777",
            "bookwithcustompk_set-0-title": "Les Fleurs du Mal",
        }

        formset = self.book_custom_pk_inlineformset(data, instance=author)
        self.assertTrue(formset.is_valid())

        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (book1,) = saved
        self.assertEqual(book1.pk, 77777)

        book1 = author.bookwithcustompk_set.get()
        self.assertEqual(book1.title, "Les Fleurs du Mal")

    def test_inline_formsets_with_multi_table_inheritance(self):
        # Test inline formsets where the inline-edited object uses multi-table
        # inheritance, thus has a non AutoField yet auto-created primary key.

        author = Author.objects.create(pk=1, name="Charles Baudelaire")

        formset = self.alternate_book_inlineformset(instance=author)
        self.assertEqual(len(formset.forms), 1)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_alternatebook_set-0-title">Title:</label>'
            '<input id="id_alternatebook_set-0-title" type="text" '
            'name="alternatebook_set-0-title" maxlength="100"></p>'
            '<p><label for="id_alternatebook_set-0-notes">Notes:</label>'
            '<input id="id_alternatebook_set-0-notes" type="text" '
            'name="alternatebook_set-0-notes" maxlength="100">'
            '<input type="hidden" name="alternatebook_set-0-author" value="1" '
            'id="id_alternatebook_set-0-author">'
            '<input type="hidden" name="alternatebook_set-0-book_ptr" '
            'id="id_alternatebook_set-0-book_ptr"></p>',
        )

        data = {
            # The number of forms rendered.
            "alternatebook_set-TOTAL_FORMS": "1",
            # The number of forms with initial data.
            "alternatebook_set-INITIAL_FORMS": "0",
            # The max number of forms.
            "alternatebook_set-MAX_NUM_FORMS": "",
            "alternatebook_set-0-title": "Flowers of Evil",
            "alternatebook_set-0-notes": "English translation of Les Fleurs du Mal",
        }

        formset = self.alternate_book_inlineformset(data, instance=author)
        self.assertTrue(formset.is_valid())

        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (book1,) = saved
        self.assertEqual(book1.title, "Flowers of Evil")
        self.assertEqual(book1.notes, "English translation of Les Fleurs du Mal")

    @skipUnlessDBFeature("supports_partially_nullable_unique_constraints")
    def test_inline_formsets_with_nullable_unique_together(self):
        # Test inline formsets where the inline-edited object has a
        # unique_together constraint with a nullable member

        author = Author.objects.create(pk=1, name="Charles Baudelaire")

        data = {
            # The number of forms rendered.
            "bookwithoptionalalteditor_set-TOTAL_FORMS": "2",
            # The number of forms with initial data.
            "bookwithoptionalalteditor_set-INITIAL_FORMS": "0",
            # The max number of forms.
            "bookwithoptionalalteditor_set-MAX_NUM_FORMS": "",
            "bookwithoptionalalteditor_set-0-author": "1",
            "bookwithoptionalalteditor_set-0-title": "Les Fleurs du Mal",
            "bookwithoptionalalteditor_set-1-author": "1",
            "bookwithoptionalalteditor_set-1-title": "Les Fleurs du Mal",
        }
        formset = self.book_alt_editor_inlineformset(data, instance=author)
        self.assertTrue(formset.is_valid())

        saved = formset.save()
        self.assertEqual(len(saved), 2)
        book1, book2 = saved
        self.assertEqual(book1.author_id, 1)
        self.assertEqual(book1.title, "Les Fleurs du Mal")
        self.assertEqual(book2.author_id, 1)
        self.assertEqual(book2.title, "Les Fleurs du Mal")

    def test_inline_formsets_with_custom_save_method(self):
        author = Author.objects.create(pk=1, name="Charles Baudelaire")
        book1 = Book.objects.create(
            pk=1, author=author, title="Les Paradis Artificiels"
        )
        book2 = Book.objects.create(pk=2, author=author, title="Les Fleurs du Mal")
        book3 = Book.objects.create(pk=3, author=author, title="Flowers of Evil")

        data = {
            "poem_set-TOTAL_FORMS": "3",  # the number of forms rendered
            "poem_set-INITIAL_FORMS": "0",  # the number of forms with initial data
            "poem_set-MAX_NUM_FORMS": "",  # the max number of forms
            "poem_set-0-name": "The Cloud in Trousers",
            "poem_set-1-name": "I",
            "poem_set-2-name": "",
        }

        poet = Poet.objects.create(name="Vladimir Mayakovsky")
        formset = self.poem_formsave_inlineformset(data=data, instance=poet)
        self.assertTrue(formset.is_valid())

        saved = formset.save()
        self.assertEqual(len(saved), 2)
        poem1, poem2 = saved
        self.assertEqual(poem1.name, "Brooklyn Bridge")
        self.assertEqual(poem2.name, "Brooklyn Bridge")

        # We can provide a custom queryset to our InlineFormSet:

        custom_qs = Book.objects.order_by("-title")
        formset = self.book_inlineformset_extra_2(instance=author, queryset=custom_qs)
        self.assertEqual(len(formset.forms), 5)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_book_set-0-title">Title:</label>'
            '<input id="id_book_set-0-title" type="text" name="book_set-0-title" '
            'value="Les Paradis Artificiels" maxlength="100">'
            '<input type="hidden" name="book_set-0-author" value="1" '
            'id="id_book_set-0-author">'
            '<input type="hidden" name="book_set-0-id" value="1" id="id_book_set-0-id">'
            "</p>",
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_book_set-1-title">Title:</label>'
            '<input id="id_book_set-1-title" type="text" name="book_set-1-title" '
            'value="Les Fleurs du Mal" maxlength="100">'
            '<input type="hidden" name="book_set-1-author" value="1" '
            'id="id_book_set-1-author">'
            '<input type="hidden" name="book_set-1-id" value="2" id="id_book_set-1-id">'
            "</p>",
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_book_set-2-title">Title:</label>'
            '<input id="id_book_set-2-title" type="text" name="book_set-2-title" '
            'value="Flowers of Evil" maxlength="100">'
            '<input type="hidden" name="book_set-2-author" value="1" '
            'id="id_book_set-2-author">'
            '<input type="hidden" name="book_set-2-id" value="3" '
            'id="id_book_set-2-id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[3].as_p(),
            '<p><label for="id_book_set-3-title">Title:</label>'
            '<input id="id_book_set-3-title" type="text" name="book_set-3-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-3-author" value="1" '
            'id="id_book_set-3-author">'
            '<input type="hidden" name="book_set-3-id" id="id_book_set-3-id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[4].as_p(),
            '<p><label for="id_book_set-4-title">Title:</label>'
            '<input id="id_book_set-4-title" type="text" name="book_set-4-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-4-author" value="1" '
            'id="id_book_set-4-author">'
            '<input type="hidden" name="book_set-4-id" id="id_book_set-4-id"></p>',
        )

        data = {
            "book_set-TOTAL_FORMS": "5",  # the number of forms rendered
            "book_set-INITIAL_FORMS": "3",  # the number of forms with initial data
            "book_set-MAX_NUM_FORMS": "",  # the max number of forms
            "book_set-0-id": str(book1.id),
            "book_set-0-title": "Les Paradis Artificiels",
            "book_set-1-id": str(book2.id),
            "book_set-1-title": "Les Fleurs du Mal",
            "book_set-2-id": str(book3.id),
            "book_set-2-title": "Flowers of Evil",
            "book_set-3-title": "Revue des deux mondes",
            "book_set-4-title": "",
        }
        formset = self.book_inlineformset_extra_2(
            data, instance=author, queryset=custom_qs
        )
        self.assertTrue(formset.is_valid())

        custom_qs = Book.objects.filter(title__startswith="F")
        formset = self.book_inlineformset_extra_2(instance=author, queryset=custom_qs)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_book_set-0-title">Title:</label>'
            '<input id="id_book_set-0-title" type="text" name="book_set-0-title" '
            'value="Flowers of Evil" maxlength="100">'
            '<input type="hidden" name="book_set-0-author" value="1" '
            'id="id_book_set-0-author">'
            '<input type="hidden" name="book_set-0-id" value="3" '
            'id="id_book_set-0-id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_book_set-1-title">Title:</label>'
            '<input id="id_book_set-1-title" type="text" name="book_set-1-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-1-author" value="1" '
            'id="id_book_set-1-author">'
            '<input type="hidden" name="book_set-1-id" id="id_book_set-1-id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_book_set-2-title">Title:</label>'
            '<input id="id_book_set-2-title" type="text" name="book_set-2-title" '
            'maxlength="100">'
            '<input type="hidden" name="book_set-2-author" value="1" '
            'id="id_book_set-2-author">'
            '<input type="hidden" name="book_set-2-id" id="id_book_set-2-id"></p>',
        )

        data = {
            "book_set-TOTAL_FORMS": "3",  # the number of forms rendered
            "book_set-INITIAL_FORMS": "1",  # the number of forms with initial data
            "book_set-MAX_NUM_FORMS": "",  # the max number of forms
            "book_set-0-id": str(book3.id),
            "book_set-0-title": "Flowers of Evil",
            "book_set-1-title": "Revue des deux mondes",
            "book_set-2-title": "",
        }
        formset = self.book_inlineformset_extra_2(
            data, instance=author, queryset=custom_qs
        )
        self.assertTrue(formset.is_valid())

    def test_inline_formsets_with_custom_save_method_related_instance(self):
        """
        The ModelForm.save() method should be able to access the related object
        if it exists in the database (#24395).
        """
        data = {
            "poem_set-TOTAL_FORMS": "1",
            "poem_set-INITIAL_FORMS": "0",
            "poem_set-MAX_NUM_FORMS": "",
            "poem_set-0-name": "Le Lac",
        }
        poet = Poet()
        formset = self.poem_formsave2_inlineformset(data=data, instance=poet)
        self.assertTrue(formset.is_valid())

        # The Poet instance is saved after the formset instantiation. This
        # happens in admin's changeform_view() when adding a new object and
        # some inlines in the same request.
        poet.name = "Lamartine"
        poet.save()
        poem = formset.save()[0]
        self.assertEqual(poem.name, "Le Lac by Lamartine")

    def test_custom_pk(self):
        # We need to ensure that it is displayed

        formset = self.custom_pk_formset()
        self.assertEqual(len(formset.forms), 1)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_form-0-my_pk">My pk:</label>'
            '<input id="id_form-0-my_pk" type="text" name="form-0-my_pk" '
            'maxlength="10"></p>'
            '<p><label for="id_form-0-some_field">Some field:</label>'
            '<input id="id_form-0-some_field" type="text" name="form-0-some_field" '
            'maxlength="100"></p>',
        )

        # Custom primary keys with ForeignKey, OneToOneField and AutoField ############

        place = Place.objects.create(pk=1, name="Giordanos", city="Chicago")

        formset = self.owner_inlineformset_extra_2(instance=place)
        self.assertEqual(len(formset.forms), 2)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_owner_set-0-name">Name:</label>'
            '<input id="id_owner_set-0-name" type="text" name="owner_set-0-name" '
            'maxlength="100">'
            '<input type="hidden" name="owner_set-0-place" value="1" '
            'id="id_owner_set-0-place">'
            '<input type="hidden" name="owner_set-0-auto_id" '
            'id="id_owner_set-0-auto_id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_owner_set-1-name">Name:</label>'
            '<input id="id_owner_set-1-name" type="text" name="owner_set-1-name" '
            'maxlength="100">'
            '<input type="hidden" name="owner_set-1-place" value="1" '
            'id="id_owner_set-1-place">'
            '<input type="hidden" name="owner_set-1-auto_id" '
            'id="id_owner_set-1-auto_id"></p>',
        )

        data = {
            "owner_set-TOTAL_FORMS": "2",
            "owner_set-INITIAL_FORMS": "0",
            "owner_set-MAX_NUM_FORMS": "",
            "owner_set-0-auto_id": "",
            "owner_set-0-name": "Joe Perry",
            "owner_set-1-auto_id": "",
            "owner_set-1-name": "",
        }
        formset = self.owner_inlineformset_extra_2(data, instance=place)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (owner1,) = saved
        self.assertEqual(owner1.name, "Joe Perry")
        self.assertEqual(owner1.place.name, "Giordanos")

        formset = self.owner_inlineformset_extra_2(instance=place)
        self.assertEqual(len(formset.forms), 3)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_owner_set-0-name">Name:</label>'
            '<input id="id_owner_set-0-name" type="text" name="owner_set-0-name" '
            'value="Joe Perry" maxlength="100">'
            '<input type="hidden" name="owner_set-0-place" value="1" '
            'id="id_owner_set-0-place">'
            '<input type="hidden" name="owner_set-0-auto_id" value="%d" '
            'id="id_owner_set-0-auto_id"></p>' % owner1.auto_id,
        )
        self.assertHTMLEqual(
            formset.forms[1].as_p(),
            '<p><label for="id_owner_set-1-name">Name:</label>'
            '<input id="id_owner_set-1-name" type="text" name="owner_set-1-name" '
            'maxlength="100">'
            '<input type="hidden" name="owner_set-1-place" value="1" '
            'id="id_owner_set-1-place">'
            '<input type="hidden" name="owner_set-1-auto_id" '
            'id="id_owner_set-1-auto_id"></p>',
        )
        self.assertHTMLEqual(
            formset.forms[2].as_p(),
            '<p><label for="id_owner_set-2-name">Name:</label>'
            '<input id="id_owner_set-2-name" type="text" name="owner_set-2-name" '
            'maxlength="100">'
            '<input type="hidden" name="owner_set-2-place" value="1" '
            'id="id_owner_set-2-place">'
            '<input type="hidden" name="owner_set-2-auto_id" '
            'id="id_owner_set-2-auto_id"></p>',
        )

        data = {
            "owner_set-TOTAL_FORMS": "3",
            "owner_set-INITIAL_FORMS": "1",
            "owner_set-MAX_NUM_FORMS": "",
            "owner_set-0-auto_id": str(owner1.auto_id),
            "owner_set-0-name": "Joe Perry",
            "owner_set-1-auto_id": "",
            "owner_set-1-name": "Jack Berry",
            "owner_set-2-auto_id": "",
            "owner_set-2-name": "",
        }
        formset = self.owner_inlineformset_extra_2(data, instance=place)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (owner2,) = saved
        self.assertEqual(owner2.name, "Jack Berry")
        self.assertEqual(owner2.place.name, "Giordanos")

        # A custom primary key that is a ForeignKey or OneToOneField get
        # rendered for the user to choose.
        formset = self.owner_profile_formset()
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_form-0-owner">Owner:</label>'
            '<select name="form-0-owner" id="id_form-0-owner">'
            '<option value="" selected>---------</option>'
            '<option value="%d">Joe Perry at Giordanos</option>'
            '<option value="%d">Jack Berry at Giordanos</option>'
            "</select></p>"
            '<p><label for="id_form-0-age">Age:</label>'
            '<input type="number" name="form-0-age" id="id_form-0-age" min="0"></p>'
            % (owner1.auto_id, owner2.auto_id),
        )

        owner1 = Owner.objects.get(name="Joe Perry")
        self.assertEqual(self.owner_profile_inlineformset.max_num, 1)

        formset = self.owner_profile_inlineformset(instance=owner1)
        self.assertEqual(len(formset.forms), 1)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_ownerprofile-0-age">Age:</label>'
            '<input type="number" name="ownerprofile-0-age" '
            'id="id_ownerprofile-0-age" min="0">'
            '<input type="hidden" name="ownerprofile-0-owner" value="%d" '
            'id="id_ownerprofile-0-owner"></p>' % owner1.auto_id,
        )

        data = {
            "ownerprofile-TOTAL_FORMS": "1",
            "ownerprofile-INITIAL_FORMS": "0",
            "ownerprofile-MAX_NUM_FORMS": "1",
            "ownerprofile-0-owner": "",
            "ownerprofile-0-age": "54",
        }
        formset = self.owner_profile_inlineformset(data, instance=owner1)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (profile1,) = saved
        self.assertEqual(profile1.owner, owner1)
        self.assertEqual(profile1.age, 54)

        formset = self.owner_profile_inlineformset(instance=owner1)
        self.assertEqual(len(formset.forms), 1)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_ownerprofile-0-age">Age:</label>'
            '<input type="number" name="ownerprofile-0-age" value="54" '
            'id="id_ownerprofile-0-age" min="0">'
            '<input type="hidden" name="ownerprofile-0-owner" value="%d" '
            'id="id_ownerprofile-0-owner"></p>' % owner1.auto_id,
        )

        data = {
            "ownerprofile-TOTAL_FORMS": "1",
            "ownerprofile-INITIAL_FORMS": "1",
            "ownerprofile-MAX_NUM_FORMS": "1",
            "ownerprofile-0-owner": str(owner1.auto_id),
            "ownerprofile-0-age": "55",
        }
        formset = self.owner_profile_inlineformset(data, instance=owner1)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (profile1,) = saved
        self.assertEqual(profile1.owner, owner1)
        self.assertEqual(profile1.age, 55)

    def test_unique_true_enforces_max_num_one(self):
        # ForeignKey with unique=True should enforce max_num=1

        place = Place.objects.create(pk=1, name="Giordanos", city="Chicago")

        self.assertEqual(self.location_inlineformset.max_num, 1)

        formset = self.location_inlineformset(instance=place)
        self.assertEqual(len(formset.forms), 1)
        self.assertHTMLEqual(
            formset.forms[0].as_p(),
            '<p><label for="id_location_set-0-lat">Lat:</label>'
            '<input id="id_location_set-0-lat" type="text" name="location_set-0-lat" '
            'maxlength="100"></p>'
            '<p><label for="id_location_set-0-lon">Lon:</label>'
            '<input id="id_location_set-0-lon" type="text" name="location_set-0-lon" '
            'maxlength="100">'
            '<input type="hidden" name="location_set-0-place" value="1" '
            'id="id_location_set-0-place">'
            '<input type="hidden" name="location_set-0-id" '
            'id="id_location_set-0-id"></p>',
        )

    def test_foreign_keys_in_parents(self):
        self.assertEqual(type(_get_foreign_key(Restaurant, Owner)), models.ForeignKey)
        self.assertEqual(
            type(_get_foreign_key(MexicanRestaurant, Owner)), models.ForeignKey
        )

    def test_unique_validation(self):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-slug": "car-red",
        }
        formset = self.product_formset_extra_1(data)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (product1,) = saved
        self.assertEqual(product1.slug, "car-red")

        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-slug": "car-red",
        }
        formset = self.product_formset_extra_1(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset.errors, [{"slug": ["Product with this Slug already exists."]}]
        )

    def test_modelformset_validate_max_flag(self):
        # If validate_max is set and max_num is less than TOTAL_FORMS in the
        # data, then throw an exception. MAX_NUM_FORMS in the data is
        # irrelevant here (it's output as a hint for the client but its
        # value in the returned data is not checked)

        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "2",  # should be ignored
            "form-0-price": "12.00",
            "form-0-quantity": "1",
            "form-1-price": "24.00",
            "form-1-quantity": "2",
        }

        formset = self.price_formset_validate_max(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(formset.non_form_errors(), ["Please submit at most 1 form."])

        # Now test the same thing without the validate_max flag to ensure
        # default behavior is unchanged
        formset = self.price_formset_no_validate_max(data)
        self.assertTrue(formset.is_valid())

    def test_modelformset_min_num_equals_max_num_less_than(self):
        data = {
            "form-TOTAL_FORMS": "3",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "2",
            "form-0-slug": "car-red",
            "form-1-slug": "car-blue",
            "form-2-slug": "car-black",
        }
        formset = self.product_formset_validate(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(formset.non_form_errors(), ["Please submit at most 2 forms."])

    def test_modelformset_min_num_equals_max_num_more_than(self):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "2",
            "form-0-slug": "car-red",
        }
        formset = self.product_formset_validate(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(formset.non_form_errors(), ["Please submit at least 2 forms."])

    def test_unique_together_validation(self):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-price": "12.00",
            "form-0-quantity": "1",
        }
        formset = self.price_formset_extra_1(data)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (price1,) = saved
        self.assertEqual(price1.price, Decimal("12.00"))
        self.assertEqual(price1.quantity, 1)

        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-price": "12.00",
            "form-0-quantity": "1",
        }
        formset = self.price_formset_extra_1(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset.errors,
            [{"__all__": ["Price with this Price and Quantity already exists."]}],
        )

    def test_unique_together_with_inlineformset_factory(self):
        # Also see bug #8882.

        repository = Repository.objects.create(name="Test Repo")
        data = {
            "revision_set-TOTAL_FORMS": "1",
            "revision_set-INITIAL_FORMS": "0",
            "revision_set-MAX_NUM_FORMS": "",
            "revision_set-0-repository": repository.pk,
            "revision_set-0-revision": "146239817507f148d448db38840db7c3cbf47c76",
            "revision_set-0-DELETE": "",
        }
        formset = self.revision_inlineformset(data, instance=repository)
        self.assertTrue(formset.is_valid())
        saved = formset.save()
        self.assertEqual(len(saved), 1)
        (revision1,) = saved
        self.assertEqual(revision1.repository, repository)
        self.assertEqual(revision1.revision, "146239817507f148d448db38840db7c3cbf47c76")

        # attempt to save the same revision against the same repo.
        data = {
            "revision_set-TOTAL_FORMS": "1",
            "revision_set-INITIAL_FORMS": "0",
            "revision_set-MAX_NUM_FORMS": "",
            "revision_set-0-repository": repository.pk,
            "revision_set-0-revision": "146239817507f148d448db38840db7c3cbf47c76",
            "revision_set-0-DELETE": "",
        }
        formset = self.revision_inlineformset(data, instance=repository)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset.errors,
            [
                {
                    "__all__": [
                        "Revision with this Repository and Revision already exists."
                    ]
                }
            ],
        )

        # unique_together with inlineformset_factory with overridden form fields
        # Also see #9494

        data = {
            "revision_set-TOTAL_FORMS": "1",
            "revision_set-INITIAL_FORMS": "0",
            "revision_set-MAX_NUM_FORMS": "",
            "revision_set-0-repository": repository.pk,
            "revision_set-0-revision": "146239817507f148d448db38840db7c3cbf47c76",
            "revision_set-0-DELETE": "",
        }
        formset = self.revision_fields_inlineformset(data, instance=repository)
        self.assertFalse(formset.is_valid())

    def test_callable_defaults(self):
        # Use of callable defaults (see bug #7975).

        person = Person.objects.create(name="Ringo")
        formset = self.membership_inlineformset(instance=person)

        # Django will render a hidden field for model fields that have a callable
        # default. This is required to ensure the value is tested for change correctly
        # when determine what extra forms have changed to save.

        self.assertEqual(len(formset.forms), 1)  # this formset only has one form
        form = formset.forms[0]
        now = form.fields["date_joined"].initial()
        result = form.as_p()
        result = re.sub(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?",
            "__DATETIME__",
            result,
        )
        self.assertHTMLEqual(
            result,
            '<p><label for="id_membership_set-0-date_joined">Date joined:</label>'
            '<input type="text" name="membership_set-0-date_joined" '
            'value="__DATETIME__" id="id_membership_set-0-date_joined">'
            '<input type="hidden" name="initial-membership_set-0-date_joined" '
            'value="__DATETIME__" '
            'id="initial-membership_set-0-id_membership_set-0-date_joined"></p>'
            '<p><label for="id_membership_set-0-karma">Karma:</label>'
            '<input type="number" name="membership_set-0-karma" '
            'id="id_membership_set-0-karma">'
            '<input type="hidden" name="membership_set-0-person" value="%d" '
            'id="id_membership_set-0-person">'
            '<input type="hidden" name="membership_set-0-id" '
            'id="id_membership_set-0-id"></p>' % person.id,
        )

        # test for validation with callable defaults. Validations rely on hidden fields

        data = {
            "membership_set-TOTAL_FORMS": "1",
            "membership_set-INITIAL_FORMS": "0",
            "membership_set-MAX_NUM_FORMS": "",
            "membership_set-0-date_joined": now.strftime("%Y-%m-%d %H:%M:%S"),
            "initial-membership_set-0-date_joined": now.strftime("%Y-%m-%d %H:%M:%S"),
            "membership_set-0-karma": "",
        }
        formset = self.membership_inlineformset(data, instance=person)
        self.assertTrue(formset.is_valid())

        # now test for when the data changes

        one_day_later = now + datetime.timedelta(days=1)
        filled_data = {
            "membership_set-TOTAL_FORMS": "1",
            "membership_set-INITIAL_FORMS": "0",
            "membership_set-MAX_NUM_FORMS": "",
            "membership_set-0-date_joined": one_day_later.strftime("%Y-%m-%d %H:%M:%S"),
            "initial-membership_set-0-date_joined": now.strftime("%Y-%m-%d %H:%M:%S"),
            "membership_set-0-karma": "",
        }
        formset = self.membership_inlineformset(filled_data, instance=person)
        self.assertFalse(formset.is_valid())

    def test_inlineformset_with_null_fk(self):
        # inlineformset factory and declarative tests
        # with fk having null=True. see #9462.
        # create some data that will exhibit the issue
        team = Team.objects.create(name="Red Vipers")
        Player(name="Timmy").save()
        Player(name="Bobby", team=team).save()

        formset = self.player_inlineformset()
        self.assertQuerySetEqual(formset.get_queryset(), [])

        formset = self.player_inlineformset(instance=team)
        players = formset.get_queryset()
        self.assertEqual(len(players), 1)
        (player1,) = players
        self.assertEqual(player1.team, team)
        self.assertEqual(player1.name, "Bobby")

    def test_inlineformset_with_arrayfield(self):
        data = {
            "book_set-TOTAL_FORMS": "3",
            "book_set-INITIAL_FORMS": "0",
            "book_set-MAX_NUM_FORMS": "",
            "book_set-0-title": "test1,test2",
            "book_set-1-title": "test1,test2",
            "book_set-2-title": "test3,test4",
        }
        author = Author.objects.create(name="test")
        formset = self.book_arrayfield_inlineformset(data, instance=author)
        self.assertEqual(
            formset.errors,
            [{}, {"__all__": ["Please correct the duplicate values below."]}, {}],
        )

    def test_model_formset_with_custom_pk(self):
        # a formset for a Model that has a custom primary key that still needs to be
        # added to the formset automatically
        self.assertEqual(
            sorted(self.classy_mexican_formset().forms[0].fields),
            ["tacos_are_yummy", "the_restaurant"],
        )

    def test_model_formset_with_initial_model_instance(self):
        # has_changed should compare model instance and primary key
        # see #18898
        john_milton = Poet(name="John Milton")
        john_milton.save()
        data = {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-MAX_NUM_FORMS": "",
            "form-0-name": "",
            "form-0-poet": str(john_milton.id),
        }
        formset = self.poem_formset(initial=[{"poet": john_milton}], data=data)
        self.assertFalse(formset.extra_forms[0].has_changed())

    def test_model_formset_with_initial_queryset(self):
        # has_changed should work with queryset and list of pk's
        # see #18898
        Author.objects.create(pk=1, name="Charles Baudelaire")
        data = {
            "form-TOTAL_FORMS": 1,
            "form-INITIAL_FORMS": 0,
            "form-MAX_NUM_FORMS": "",
            "form-0-name": "",
            "form-0-created": "",
            "form-0-authors": list(Author.objects.values_list("id", flat=True)),
        }
        formset = self.author_meeting_formset(
            initial=[{"authors": Author.objects.all()}], data=data
        )
        self.assertFalse(formset.extra_forms[0].has_changed())

    def test_prevent_duplicates_from_with_the_same_formset(self):
        data = {
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 0,
            "form-MAX_NUM_FORMS": "",
            "form-0-slug": "red_car",
            "form-1-slug": "red_car",
        }
        formset = self.product_formset_extra_2(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset._non_form_errors, ["Please correct the duplicate data for slug."]
        )

        data = {
            "form-TOTAL_FORMS": 2,
            "form-INITIAL_FORMS": 0,
            "form-MAX_NUM_FORMS": "",
            "form-0-price": "25",
            "form-0-quantity": "7",
            "form-1-price": "25",
            "form-1-quantity": "7",
        }
        formset = self.price_formset_extra_2(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset._non_form_errors,
            [
                "Please correct the duplicate data for price and quantity, which must "
                "be unique."
            ],
        )

        # Only the price field is specified, this should skip any unique
        # checks since the unique_together is not fulfilled. This will fail
        # with a KeyError if broken.
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-price": "24",
            "form-1-price": "24",
        }
        formset = self.price_formset_fields(data)
        self.assertTrue(formset.is_valid())

        author = Author.objects.create(pk=1, name="Charles Baudelaire")
        Book.objects.create(pk=1, author=author, title="Les Paradis Artificiels")
        Book.objects.create(pk=2, author=author, title="Les Fleurs du Mal")
        Book.objects.create(pk=3, author=author, title="Flowers of Evil")

        book_ids = author.book_set.order_by("id").values_list("id", flat=True)
        data = {
            "book_set-TOTAL_FORMS": "2",
            "book_set-INITIAL_FORMS": "2",
            "book_set-MAX_NUM_FORMS": "",
            "book_set-0-title": "The 2008 Election",
            "book_set-0-author": str(author.id),
            "book_set-0-id": str(book_ids[0]),
            "book_set-1-title": "The 2008 Election",
            "book_set-1-author": str(author.id),
            "book_set-1-id": str(book_ids[1]),
        }
        formset = self.book_inlineformset_extra_0(data=data, instance=author)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset._non_form_errors, ["Please correct the duplicate data for title."]
        )
        self.assertEqual(
            formset.errors,
            [{}, {"__all__": ["Please correct the duplicate values below."]}],
        )

        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-title": "blah",
            "form-0-slug": "Morning",
            "form-0-subtitle": "foo",
            "form-0-posted": "2009-01-01",
            "form-1-title": "blah",
            "form-1-slug": "Morning in Prague",
            "form-1-subtitle": "rawr",
            "form-1-posted": "2009-01-01",
        }
        formset = self.post_formset_extra_2(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset._non_form_errors,
            [
                "Please correct the duplicate data for title which must be unique for "
                "the date in posted."
            ],
        )
        self.assertEqual(
            formset.errors,
            [{}, {"__all__": ["Please correct the duplicate values below."]}],
        )

        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-title": "foo",
            "form-0-slug": "Morning in Prague",
            "form-0-subtitle": "foo",
            "form-0-posted": "2009-01-01",
            "form-1-title": "blah",
            "form-1-slug": "Morning in Prague",
            "form-1-subtitle": "rawr",
            "form-1-posted": "2009-08-02",
        }
        formset = self.post_formset_extra_2(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset._non_form_errors,
            [
                "Please correct the duplicate data for slug which must be unique for "
                "the year in posted."
            ],
        )

        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "",
            "form-0-title": "foo",
            "form-0-slug": "Morning in Prague",
            "form-0-subtitle": "rawr",
            "form-0-posted": "2008-08-01",
            "form-1-title": "blah",
            "form-1-slug": "Prague",
            "form-1-subtitle": "rawr",
            "form-1-posted": "2009-08-02",
        }
        formset = self.post_formset_extra_2(data)
        self.assertFalse(formset.is_valid())
        self.assertEqual(
            formset._non_form_errors,
            [
                "Please correct the duplicate data for subtitle which must be unique "
                "for the month in posted."
            ],
        )

    def test_prevent_change_outer_model_and_create_invalid_data(self):
        author = Author.objects.create(name="Charles")
        other_author = Author.objects.create(name="Walt")
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "2",
            "form-MAX_NUM_FORMS": "",
            "form-0-id": str(author.id),
            "form-0-name": "Charles",
            "form-1-id": str(other_author.id),  # A model not in the formset's queryset.
            "form-1-name": "Changed name",
        }
        # This formset is only for Walt Whitman and shouldn't accept data for
        # other_author.
        formset = self.author_formset(
            data=data, queryset=Author.objects.filter(id__in=(author.id,))
        )
        self.assertTrue(formset.is_valid())
        formset.save()
        # The name of other_author shouldn't be changed and new models aren't
        # created.
        self.assertSequenceEqual(Author.objects.all(), [author, other_author])

    def test_validation_without_id(self):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "",
            "form-0-name": "Charles",
        }
        formset = self.author_formset(data)
        self.assertEqual(
            formset.errors,
            [{"id": ["This field is required."]}],
        )

    def test_validation_with_child_model_without_id(self):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "",
            "form-0-name": "Charles",
            "form-0-write_speed": "10",
        }
        formset = self.better_author_formset(data)
        self.assertEqual(
            formset.errors,
            [{"author_ptr": ["This field is required."]}],
        )

    def test_validation_with_invalid_id(self):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "",
            "form-0-id": "abc",
            "form-0-name": "Charles",
        }
        formset = self.author_formset(data)
        self.assertEqual(
            formset.errors,
            [
                {
                    "id": [
                        "Select a valid choice. That choice is not one of the "
                        "available choices."
                    ]
                }
            ],
        )

    def test_validation_with_nonexistent_id(self):
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "",
            "form-0-id": "12345",
            "form-0-name": "Charles",
        }
        formset = self.author_formset(data)
        self.assertEqual(
            formset.errors,
            [
                {
                    "id": [
                        "Select a valid choice. That choice is not one of the "
                        "available choices."
                    ]
                }
            ],
        )

    def test_initial_form_count_empty_data(self):
        formset = self.author_formset({})
        self.assertEqual(formset.initial_form_count(), 0)

    def test_edit_only(self):
        charles = Author.objects.create(name="Charles Baudelaire")
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "0",
            "form-0-name": "Arthur Rimbaud",
            "form-1-name": "Walt Whitman",
        }
        formset = self.author_formset_edit_only(data)
        self.assertIs(formset.is_valid(), True)
        formset.save()
        self.assertSequenceEqual(Author.objects.all(), [charles])
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "0",
            "form-0-id": charles.pk,
            "form-0-name": "Arthur Rimbaud",
            "form-1-name": "Walt Whitman",
        }
        formset = self.author_formset_edit_only(data)
        self.assertIs(formset.is_valid(), True)
        formset.save()
        charles.refresh_from_db()
        self.assertEqual(charles.name, "Arthur Rimbaud")
        self.assertSequenceEqual(Author.objects.all(), [charles])

    def test_edit_only_inlineformset_factory(self):
        charles = Author.objects.create(name="Charles Baudelaire")
        book = Book.objects.create(author=charles, title="Les Paradis Artificiels")
        data = {
            "book_set-TOTAL_FORMS": "4",
            "book_set-INITIAL_FORMS": "1",
            "book_set-MAX_NUM_FORMS": "0",
            "book_set-0-id": book.pk,
            "book_set-0-title": "Les Fleurs du Mal",
            "book_set-0-author": charles.pk,
            "book_set-1-title": "Flowers of Evil",
            "book_set-1-author": charles.pk,
        }
        formset = self.book_inlineformset_edit_only(data, instance=charles)
        self.assertIs(formset.is_valid(), True)
        formset.save()
        book.refresh_from_db()
        self.assertEqual(book.title, "Les Fleurs du Mal")
        self.assertSequenceEqual(Book.objects.all(), [book])

    def test_edit_only_object_outside_of_queryset(self):
        charles = Author.objects.create(name="Charles Baudelaire")
        walt = Author.objects.create(name="Walt Whitman")
        data = {
            "form-TOTAL_FORMS": "1",
            "form-INITIAL_FORMS": "1",
            "form-0-id": walt.pk,
            "form-0-name": "Parth Patil",
        }
        formset = self.author_formset_edit_only(
            data, queryset=Author.objects.filter(pk=charles.pk)
        )
        self.assertIs(formset.is_valid(), True)
        formset.save()
        self.assertCountEqual(Author.objects.all(), [charles, walt])

    def test_edit_only_formset_factory_with_basemodelformset(self):
        charles = Author.objects.create(name="Charles Baudelaire")

        class AuthorForm(forms.ModelForm):
            class Meta:
                model = Author
                fields = "__all__"

        class BaseAuthorFormSet(BaseModelFormSet):
            def __init__(self, *args, **kwargs):
                self.model = Author
                super().__init__(*args, **kwargs)

        AuthorFormSet = formset_factory(AuthorForm, formset=BaseAuthorFormSet)
        data = {
            "form-TOTAL_FORMS": "2",
            "form-INITIAL_FORMS": "1",
            "form-MAX_NUM_FORMS": "0",
            "form-0-id": charles.pk,
            "form-0-name": "Shawn Dong",
            "form-1-name": "Walt Whitman",
        }
        formset = AuthorFormSet(data)
        self.assertIs(formset.is_valid(), True)
        formset.save()
        self.assertEqual(Author.objects.count(), 2)
        charles.refresh_from_db()
        self.assertEqual(charles.name, "Shawn Dong")
        self.assertEqual(Author.objects.count(), 2)

    def test_custom_clean_poem_formset(self):
        """A custom clean poem formset."""
        data = {"name": "AN UPPERCASE NAME"}
        data = {
            "poems-INITIAL_FORMS": "0",
            "poems-TOTAL_FORMS": "1",
            "poems-0-name": "AN UPPERCASE NAME",
        }
        formset = self.poem_custom_inlineformset(data=data, prefix="poems")
        formset.full_clean()
        self.assertTrue(formset.is_valid())
        self.assertEqual(formset.forms[0].clean().get("name"), "an uppercase name")


class FactoryModelFormsetTest(TestCase, ModelFormsetTestMixin):
    """A set of tests of modelformsets and inlineformset.

    Created with factories.
    """

    # modelformsets
    author_formset_extra_3 = modelformset_factory(Author, fields="__all__", extra=3)
    author_formset_delete_false = modelformset_factory(
        Author, fields="__all__", extra=1, can_delete=False
    )
    author_formset_delete_true = modelformset_factory(
        Author, fields="__all__", extra=1, can_delete=True
    )
    author_meeting_delete_true = modelformset_factory(
        AuthorMeeting, fields="__all__", extra=1, can_delete=True
    )
    author_formset_no_max = modelformset_factory(
        Author, fields="__all__", max_num=None, extra=3
    )
    author_formset_max_greater = modelformset_factory(
        Author, fields="__all__", max_num=4, extra=3
    )
    author_formset_max_0_extra = modelformset_factory(
        Author, fields="__all__", max_num=0, extra=3
    )
    author_formset_max_none = modelformset_factory(
        Author, fields="__all__", max_num=None
    )
    author_formset_max_0 = modelformset_factory(Author, fields="__all__", max_num=0)
    author_formset_max = modelformset_factory(Author, fields="__all__", max_num=4)
    author_formset_extra_0 = modelformset_factory(Author, fields="__all__", extra=0)
    author_formset_min_greater = modelformset_factory(
        Author, fields="__all__", min_num=1, extra=0
    )
    author_formset_same_min_extra = modelformset_factory(
        Author, fields="__all__", min_num=1, extra=1
    )
    poet_formset_model_and_form = modelformset_factory(
        Poet, fields="__all__", form=PoetForm
    )
    post_formset_form1 = modelformset_factory(Post, form=PostForm1)
    post_formset_form2 = modelformset_factory(Post, form=PostForm2)
    author_formset_custom_base = modelformset_factory(
        Author, fields="__all__", formset=BaseAuthorFormSet
    )
    better_author_formset = modelformset_factory(BetterAuthor, fields="__all__")
    custom_pk_formset = modelformset_factory(CustomPrimaryKey, fields="__all__")
    owner_profile_formset = modelformset_factory(OwnerProfile, fields="__all__")
    product_formset_extra_1 = modelformset_factory(Product, fields="__all__", extra=1)
    price_formset_validate_max = modelformset_factory(
        Price, fields="__all__", extra=1, max_num=1, validate_max=True
    )
    price_formset_no_validate_max = modelformset_factory(
        Price, fields="__all__", extra=1, max_num=1
    )
    product_formset_validate = modelformset_factory(
        Product,
        fields="__all__",
        extra=1,
        max_num=2,
        validate_max=True,
        min_num=2,
        validate_min=True,
    )
    price_formset_extra_1 = modelformset_factory(Price, fields="__all__", extra=1)
    classy_mexican_formset = modelformset_factory(
        ClassyMexicanRestaurant, fields=["tacos_are_yummy"]
    )
    poem_formset = modelformset_factory(Poem, fields="__all__")
    author_meeting_formset = modelformset_factory(AuthorMeeting, fields="__all__")
    product_formset_extra_2 = modelformset_factory(Product, fields="__all__", extra=2)
    price_formset_extra_2 = modelformset_factory(Price, fields="__all__", extra=2)
    price_formset_fields = modelformset_factory(Price, fields=("price",), extra=2)
    post_formset_extra_2 = modelformset_factory(Post, fields="__all__", extra=2)
    author_formset = modelformset_factory(Author, fields="__all__")
    author_formset_edit_only = modelformset_factory(
        Author, fields="__all__", edit_only=True
    )
    # inlineformsets
    book_inlineformset_extra_3 = inlineformset_factory(
        Author, Book, can_delete=False, extra=3, fields="__all__"
    )
    book_inlineformset_extra_2 = inlineformset_factory(
        Author, Book, can_delete=False, extra=2, fields="__all__"
    )
    book_custom_pk_inlineformset = inlineformset_factory(
        Author, BookWithCustomPK, can_delete=False, extra=1, fields="__all__"
    )
    alternate_book_inlineformset = inlineformset_factory(
        Author, AlternateBook, can_delete=False, extra=1, fields="__all__"
    )
    book_alt_editor_inlineformset = inlineformset_factory(
        Author,
        BookWithOptionalAltEditor,
        can_delete=False,
        extra=2,
        fields="__all__",
    )
    poem_formsave_inlineformset = inlineformset_factory(
        Poet, Poem, form=PoemFormSave, fields="__all__"
    )
    poem_formsave2_inlineformset = inlineformset_factory(
        Poet, Poem, form=PoemFormSave2, fields="__all__"
    )
    owner_inlineformset_extra_2 = inlineformset_factory(
        Place, Owner, extra=2, can_delete=False, fields="__all__"
    )
    owner_profile_inlineformset = inlineformset_factory(
        Owner, OwnerProfile, max_num=1, can_delete=False, fields="__all__"
    )
    location_inlineformset = inlineformset_factory(
        Place, Location, can_delete=False, fields="__all__"
    )
    revision_inlineformset = inlineformset_factory(
        Repository, Revision, extra=1, fields="__all__"
    )
    revision_fields_inlineformset = inlineformset_factory(
        Repository, Revision, fields=("revision",), extra=1
    )
    membership_inlineformset = inlineformset_factory(
        Person, Membership, can_delete=False, extra=1, fields="__all__"
    )
    player_inlineformset = inlineformset_factory(Team, Player, fields="__all__")
    book_arrayfield_inlineformset = inlineformset_factory(
        Author, Book, form=BookFormArrayField
    )
    book_inlineformset_extra_0 = inlineformset_factory(
        Author, Book, extra=0, fields="__all__"
    )
    book_inlineformset_edit_only = inlineformset_factory(
        Author,
        Book,
        can_delete=False,
        fields="__all__",
        edit_only=True,
    )
    poem_custom_inlineformset = inlineformset_factory(
        Poet, Poem, form=PoemFormField, formset=CustomInlineFormSet
    )

    def test_modelformset_without_fields(self):
        """Regression for #19733."""
        message = (
            "Calling modelformset_factory without defining 'fields' or 'exclude' "
            "explicitly is prohibited."
        )
        with self.assertRaisesMessage(ImproperlyConfigured, message):
            modelformset_factory(Author)

    def test_inline_formsets_with_wrong_fk_name(self):
        """Regression for #23451."""
        message = "fk_name 'title' is not a ForeignKey to 'model_formsets.Author'."
        with self.assertRaisesMessage(ValueError, message):
            inlineformset_factory(Author, Book, fields="__all__", fk_name="title")

    def test_callable_defaults_split_datetime(self):
        # Use of callable defaults with split datetime fields.
        person = Person.objects.create(name="Ringo")
        formset = self.membership_inlineformset(instance=person)
        form = formset.forms[0]
        now = form.fields["date_joined"].initial()

        class MembershipForm(forms.ModelForm):
            date_joined = forms.SplitDateTimeField(initial=now)

            class Meta:
                model = Membership
                fields = "__all__"

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.fields["date_joined"].widget = forms.SplitDateTimeWidget()

        FormSet = inlineformset_factory(
            Person,
            Membership,
            form=MembershipForm,
            can_delete=False,
            extra=1,
            fields="__all__",
        )
        data = {
            "membership_set-TOTAL_FORMS": "1",
            "membership_set-INITIAL_FORMS": "0",
            "membership_set-MAX_NUM_FORMS": "",
            "membership_set-0-date_joined_0": now.strftime("%Y-%m-%d"),
            "membership_set-0-date_joined_1": now.strftime("%H:%M:%S"),
            "initial-membership_set-0-date_joined": now.strftime("%Y-%m-%d %H:%M:%S"),
            "membership_set-0-karma": "",
        }
        formset = FormSet(data, instance=person)
        self.assertTrue(formset.is_valid())

    def test_no_model_argument_error(self):
        """Test that modelformset can not be created without a model argument."""
        msg = "modelformset_factory() missing 1 required positional argument: 'model'"
        with self.assertRaisesMessage(TypeError, msg):
            modelformset_factory(fields="__all__")

    def test_no_model_but_form_argument_error(self):
        """
        Test that modelformset can not be created without a model argument,
        even if you pass a form argument.
        """
        msg = "modelformset_factory() missing 1 required positional argument: 'model'"
        with self.assertRaisesMessage(TypeError, msg):
            modelformset_factory(form=PoetForm)

    def test_model_no_fields_or_exclude_arguments_error(self):
        """
        Test that modelformset can not be created if you pass a model but
        without fields or exclude arguments or a form.
        """
        with self.assertRaises(ImproperlyConfigured):
            modelformset_factory(model=Post)

    def test_no_parent_model_inline_argument_error(self):
        """Test that inlineformset can not be created without a parent_model."""
        msg = "inlineformset_factory() missing 1 required positional "
        "argument: 'parent_model'"
        with self.assertRaisesMessage(TypeError, msg):
            inlineformset_factory(model=Poem, form=PoemFormSave)

    def test_no_model_inline_argument_error(self):
        """Test that inlineformset can not be created without a model argument."""
        msg = "inlineformset_factory() missing 1 required positional argument: 'model'"
        with self.assertRaisesMessage(TypeError, msg):
            inlineformset_factory(parent_model=Poet, form=PoemFormSave)


class DeclarativeModelFormsetTest(TestCase, ModelFormsetTestMixin):
    """A set of tests of modelformsets created with declarative syntax."""

    class DeclarativeAuthorFormSetExtra3(ModelFormSet):
        model = Author
        fields = "__all__"
        extra = 3

    class DeclarativeAuthorFormSetDeleteFalse(ModelFormSet):
        model = Author
        fields = "__all__"
        extra = 1
        can_delete = False

    class DeclarativeAuthorFormSetDeleteTrue(ModelFormSet):
        model = Author
        fields = "__all__"
        extra = 1
        can_delete = True

    class DeclarativeAuthorMeetingFormSetDelete(ModelFormSet):
        model = AuthorMeeting
        fields = "__all__"
        extra = 1
        can_delete = True

    class DeclarativeAuthorFormSetNoMax(ModelFormSet):
        model = Author
        fields = "__all__"
        max_num = None
        extra = 3

    class DeclarativeAuthorFormSetMaxGreater(ModelFormSet):
        model = Author
        fields = "__all__"
        max_num = 4
        extra = 3

    class DeclarativeAuthorFormSetMax0Extra(ModelFormSet):
        model = Author
        fields = "__all__"
        max_num = 0
        extra = 3

    class DeclarativeAuthorFormSetMaxNone(ModelFormSet):
        model = Author
        fields = "__all__"
        max_num = None

    class DeclarativeAuthorFormSetMax0(ModelFormSet):
        model = Author
        fields = "__all__"
        max_num = 0

    class DeclarativeAuthorFormSetMax(ModelFormSet):
        model = Author
        fields = "__all__"
        max_num = 4

    class DeclarativeAuthorFormSetExtra0(ModelFormSet):
        model = Author
        fields = "__all__"
        extra = 0

    class DeclarativeAuthorFormSetMinGreater(ModelFormSet):
        model = Author
        fields = "__all__"
        min_num = 1
        extra = 0

    class DeclarativeAuthorFormSetSameMinExtra(ModelFormSet):
        model = Author
        fields = "__all__"
        min_num = 1
        extra = 1

    class DeclarativePoetFormSetWithForm(ModelFormSet):
        model = Poet
        fields = "__all__"
        form = PoetForm

    class DeclarativePostFormSetPostForm1(ModelFormSet):
        model = Post
        form = PostForm1

    class DeclarativePostFormSetPostForm2(ModelFormSet):
        model = Post
        form = PostForm2

    class DeclarativeAuthorFormSetCustomBase(ModelFormSet):
        model = Author
        fields = "__all__"

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.queryset = Author.objects.filter(name__startswith="Charles")

    class DeclarativeBetterAuthorFormSet(ModelFormSet):
        model = BetterAuthor
        fields = "__all__"

    class DeclarativeCustomPrimaryKeyFormSet(ModelFormSet):
        model = CustomPrimaryKey
        fields = "__all__"

    class DeclarativeOwnerProfileFormSet(ModelFormSet):
        model = OwnerProfile
        fields = "__all__"

    class DeclarativeProductFormSetExtra1(ModelFormSet):
        model = Product
        fields = "__all__"
        extra = 1

    class DeclarativePriceFormSetValidateMax(ModelFormSet):
        model = Price
        fields = "__all__"
        extra = 1
        max_num = 1
        validate_max = True

    class DeclarativePriceFormSetNoValidateMax(ModelFormSet):
        model = Price
        fields = "__all__"
        extra = 1
        max_num = 1

    class DeclarativeProductFormSetValidate(ModelFormSet):
        model = Product
        fields = "__all__"
        extra = 1
        max_num = 2
        validate_max = True
        min_num = 2
        validate_min = True

    class DeclarativePriceFormSetExtra1(ModelFormSet):
        model = Price
        fields = "__all__"
        extra = 1

    class DeclarativeClassyMexicanFormSet(ModelFormSet):
        model = ClassyMexicanRestaurant
        fields = ["tacos_are_yummy"]

    class DeclarativePoemFormSet(ModelFormSet):
        model = Poem
        fields = "__all__"

    class DeclarativeAuthorMeetingFormSet(ModelFormSet):
        model = AuthorMeeting
        fields = "__all__"

    class DeclarativeProductFormSetExtra2(ModelFormSet):
        model = Product
        fields = "__all__"
        extra = 2

    class DeclarativePriceFormSetExtra2(ModelFormSet):
        model = Price
        fields = "__all__"
        extra = 2

    class DeclarativePriceFormSetFields(ModelFormSet):
        model = Price
        fields = ("price",)
        extra = 2

    class DeclarativePostFormSetExtra2(ModelFormSet):
        model = Post
        fields = "__all__"
        extra = 2

    class DeclarativeAuthorFormSet(ModelFormSet):
        model = Author
        fields = "__all__"

    class DeclarativeAuthorFormSetEditOnly(ModelFormSet):
        model = Author
        fields = "__all__"
        edit_only = True

    class DeclarativeBookInlineSetExtra3(InlineFormSet):
        """A declarative book inlineformset."""

        parent_model = Author
        model = Book
        can_delete = False
        extra = 3
        fields = "__all__"

    class DeclarativeBookInlineSetExtra2(InlineFormSet):
        """A declarative book inlineformset."""

        parent_model = Author
        model = Book
        can_delete = False
        extra = 2
        fields = "__all__"

    class DeclarativeBookCustomInlineSet(InlineFormSet):
        """A declarative book with custom pk inlineformset."""

        parent_model = Author
        model = BookWithCustomPK
        can_delete = False
        extra = 1
        fields = "__all__"

    class DeclarativeAlternateBookInlineSet(InlineFormSet):
        """A declarative alternate book inlineformset."""

        parent_model = Author
        model = AlternateBook
        can_delete = False
        extra = 1
        fields = "__all__"

    class DeclarativeBookAltEditorInlineSet(InlineFormSet):
        """A declarative book with optional alt editor inlineformset."""

        parent_model = Author
        model = BookWithOptionalAltEditor
        can_delete = False
        extra = 2
        fields = "__all__"

    class DeclarativePoemFormSaveInlineSet(InlineFormSet):
        """A declarative poem inlineformset."""

        parent_model = Poet
        model = Poem
        form = PoemFormSave
        fields = "__all__"

    class DeclarativePoemFormSave2InlineSet(InlineFormSet):
        """A declarative poem inlineformset."""

        parent_model = Poet
        model = Poem
        form = PoemFormSave2
        fields = "__all__"

    class DeclarativeOwnerInlineSetExtra2(InlineFormSet):
        """A declarative owner inlineformset."""

        parent_model = Place
        model = Owner
        extra = 2
        can_delete = False
        fields = "__all__"

    class DeclarativeOwnerProfileInlineSet(InlineFormSet):
        """A declarative owner profile inlineformset."""

        parent_model = Owner
        model = OwnerProfile
        max_num = 1
        can_delete = False
        fields = "__all__"

    class DeclarativeLocationInlineSet(InlineFormSet):
        """A declarative location inlineformset."""

        parent_model = Place
        model = Location
        can_delete = False
        fields = "__all__"

    class DeclarativeRevisionInlineSet(InlineFormSet):
        """A declarative revision inlineformset."""

        parent_model = Repository
        model = Revision
        extra = 1
        fields = "__all__"

    class DeclarativeRevisionFieldsInlineSet(InlineFormSet):
        """A declarative revision with overridden form fields inlineformset."""

        parent_model = Repository
        model = Revision
        fields = ("revision",)
        extra = 1

    class DeclarativeMembershipInlineSet(InlineFormSet):
        """A declarative membership inlineformset."""

        parent_model = Person
        model = Membership
        can_delete = False
        extra = 1
        fields = "__all__"

    class DeclarativePlayerInlineSet(InlineFormSet):
        """A declarative player inlineformset."""

        parent_model = Team
        model = Player
        fields = "__all__"

    class DeclarativeBookArrayFieldInlineSet(InlineFormSet):
        """A declarative book with arrayfield inlineformset."""

        parent_model = Author
        model = Book
        form = BookFormArrayField

    class DeclarativeBookInlineSetExtra0(InlineFormSet):
        """A declarative book inlineformset."""

        parent_model = Author
        model = Book
        extra = 0
        fields = "__all__"

    class DeclarativeBookEditOnlyInlineSet(InlineFormSet):
        """A declarative book edit only inlineformset."""

        parent_model = Author
        model = Book
        can_delete = False
        fields = "__all__"
        edit_only = True

    class DeclarativeCustomPoemInlineFormSet(InlineFormSet):
        """A declarative custom poem inlineformset."""

        parent_model = Poet
        model = Poem
        form = PoemFormField

        def clean(self):
            """Clean method."""
            for comment in self.cleaned_data:
                comment["name"] = comment["name"].lower()
            super().clean()

    # modelformsets
    author_formset_extra_3 = DeclarativeAuthorFormSetExtra3
    author_formset_delete_false = DeclarativeAuthorFormSetDeleteFalse
    author_formset_delete_true = DeclarativeAuthorFormSetDeleteTrue
    author_meeting_delete_true = DeclarativeAuthorMeetingFormSetDelete
    author_formset_no_max = DeclarativeAuthorFormSetNoMax
    author_formset_max_greater = DeclarativeAuthorFormSetMaxGreater
    author_formset_max_0_extra = DeclarativeAuthorFormSetMax0Extra
    author_formset_max_none = DeclarativeAuthorFormSetMaxNone
    author_formset_max_0 = DeclarativeAuthorFormSetMax0
    author_formset_max = DeclarativeAuthorFormSetMax
    author_formset_extra_0 = DeclarativeAuthorFormSetExtra0
    author_formset_min_greater = DeclarativeAuthorFormSetMinGreater
    author_formset_same_min_extra = DeclarativeAuthorFormSetSameMinExtra
    poet_formset_model_and_form = DeclarativePoetFormSetWithForm
    post_formset_form1 = DeclarativePostFormSetPostForm1
    post_formset_form2 = DeclarativePostFormSetPostForm2
    author_formset_custom_base = DeclarativeAuthorFormSetCustomBase
    better_author_formset = DeclarativeBetterAuthorFormSet
    custom_pk_formset = DeclarativeCustomPrimaryKeyFormSet
    owner_profile_formset = DeclarativeOwnerProfileFormSet
    product_formset_extra_1 = DeclarativeProductFormSetExtra1
    price_formset_validate_max = DeclarativePriceFormSetValidateMax
    price_formset_no_validate_max = DeclarativePriceFormSetNoValidateMax
    product_formset_validate = DeclarativeProductFormSetValidate
    price_formset_extra_1 = DeclarativePriceFormSetExtra1
    classy_mexican_formset = DeclarativeClassyMexicanFormSet
    poem_formset = DeclarativePoemFormSet
    author_meeting_formset = DeclarativeAuthorMeetingFormSet
    product_formset_extra_2 = DeclarativeProductFormSetExtra2
    price_formset_extra_2 = DeclarativePriceFormSetExtra2
    price_formset_fields = DeclarativePriceFormSetFields
    post_formset_extra_2 = DeclarativePostFormSetExtra2
    author_formset = DeclarativeAuthorFormSet
    author_formset_edit_only = DeclarativeAuthorFormSetEditOnly
    # inlineformsets
    book_inlineformset_extra_3 = DeclarativeBookInlineSetExtra3
    book_inlineformset_extra_2 = DeclarativeBookInlineSetExtra2
    book_custom_pk_inlineformset = DeclarativeBookCustomInlineSet
    alternate_book_inlineformset = DeclarativeAlternateBookInlineSet
    book_alt_editor_inlineformset = DeclarativeBookAltEditorInlineSet
    poem_formsave_inlineformset = DeclarativePoemFormSaveInlineSet
    poem_formsave2_inlineformset = DeclarativePoemFormSave2InlineSet
    owner_inlineformset_extra_2 = DeclarativeOwnerInlineSetExtra2
    owner_profile_inlineformset = DeclarativeOwnerProfileInlineSet
    location_inlineformset = DeclarativeLocationInlineSet
    revision_inlineformset = DeclarativeRevisionInlineSet
    revision_fields_inlineformset = DeclarativeRevisionFieldsInlineSet
    membership_inlineformset = DeclarativeMembershipInlineSet
    player_inlineformset = DeclarativePlayerInlineSet
    book_arrayfield_inlineformset = DeclarativeBookArrayFieldInlineSet
    book_inlineformset_extra_0 = DeclarativeBookInlineSetExtra0
    book_inlineformset_edit_only = DeclarativeBookEditOnlyInlineSet
    poem_custom_inlineformset = DeclarativeCustomPoemInlineFormSet

    def test_modelformset_without_fields(self):
        """Regression for #19733."""
        message = (
            "Calling modelform_factory without defining 'fields' "
            "or 'exclude' explicitly is prohibited."
        )
        with self.assertRaisesMessage(ImproperlyConfigured, message):

            class DeclarativeInvalidAuthorFormSet(ModelFormSet):
                model = Author

    def test_inline_formsets_with_wrong_fk_name(self):
        """Regression for #23451."""
        message = "fk_name 'title' is not a ForeignKey to 'model_formsets.Author'."
        with self.assertRaisesMessage(ValueError, message):

            class DeclarativeInvalidBookInlineSet(InlineFormSet):
                parent_model = Author
                model = Book
                fields = "__all__"
                fk_name = "title"

    def test_callable_defaults_split_datetime(self):
        # Use of callable defaults with split datetime fields.
        person = Person.objects.create(name="Ringo")
        formset = self.membership_inlineformset(instance=person)
        form = formset.forms[0]
        now = form.fields["date_joined"].initial()

        class MembershipForm(forms.ModelForm):
            date_joined = forms.SplitDateTimeField(initial=now)

            class Meta:
                model = Membership
                fields = "__all__"

            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.fields["date_joined"].widget = forms.SplitDateTimeWidget()

        class DeclarativeMembershipFormInlineSet(InlineFormSet):
            """A declarative membership with form inlineformset."""

            parent_model = Person
            model = Membership
            form = MembershipForm
            can_delete = False
            extra = 1
            fields = "__all__"

        data = {
            "membership_set-TOTAL_FORMS": "1",
            "membership_set-INITIAL_FORMS": "0",
            "membership_set-MAX_NUM_FORMS": "",
            "membership_set-0-date_joined_0": now.strftime("%Y-%m-%d"),
            "membership_set-0-date_joined_1": now.strftime("%H:%M:%S"),
            "initial-membership_set-0-date_joined": now.strftime("%Y-%m-%d %H:%M:%S"),
            "membership_set-0-karma": "",
        }
        formset = DeclarativeMembershipFormInlineSet(data, instance=person)
        self.assertTrue(formset.is_valid())

    def test_no_model_argument_error(self):
        """Test that modelformset can not be created without a model argument."""
        msg = "ModelFormSet() missing 1 required positional argument: 'model'"
        with self.assertRaisesMessage(TypeError, msg):

            class DeclarativeInvalidFormSet(ModelFormSet):
                fields = "__all__"

    def test_no_model_but_form_argument_error(self):
        """
        Test that modelformset can not be created without a model argument,
        even if you pass a form argument.
        """
        msg = "ModelFormSet() missing 1 required positional argument: 'model'"
        with self.assertRaisesMessage(TypeError, msg):

            class DeclarativeInvalidFormSet(ModelFormSet):
                form = PoetForm

    def test_model_no_fields_or_exclude_arguments_error(self):
        """
        Test that modelformset can not be created if you pass a model but
        without fields or exclude arguments or a form.
        """
        with self.assertRaises(ImproperlyConfigured):

            class DeclarativeInvalidFormSet(ModelFormSet):
                model = Post

    def test_no_parent_model_inline_argument_error(self):
        """Test that inlineformset can not be created without a parent_model."""
        msg = "InlineFormSet() missing 1 required positional argument: 'parent_model'"
        with self.assertRaisesMessage(TypeError, msg):

            class DeclarativeInvalidInlineFormSet(InlineFormSet):
                model = Poem
                form = PoemFormSave

    def test_no_model_inline_argument_error(self):
        """Test that inlineformset can not be created without a model argument."""
        msg = "InlineFormSet() missing 1 required positional argument: 'model'"
        with self.assertRaisesMessage(TypeError, msg):

            class DeclarativeInvalidInlineFormSet(InlineFormSet):
                parent_model = Poet
                form = PoemFormSave


class TestModelFormsetOverridesTroughFormMeta(TestCase):
    def test_modelformset_factory_widgets(self):
        widgets = {"name": forms.TextInput(attrs={"class": "poet"})}
        PoetFormSet = modelformset_factory(Poet, fields="__all__", widgets=widgets)
        form = PoetFormSet.form()
        self.assertHTMLEqual(
            str(form["name"]),
            '<input id="id_name" maxlength="100" type="text" class="poet" name="name" '
            "required>",
        )

    def test_inlineformset_factory_widgets(self):
        widgets = {"title": forms.TextInput(attrs={"class": "book"})}
        BookFormSet = inlineformset_factory(
            Author, Book, widgets=widgets, fields="__all__"
        )
        form = BookFormSet.form()
        self.assertHTMLEqual(
            str(form["title"]),
            '<input class="book" id="id_title" maxlength="100" name="title" '
            'type="text" required>',
        )

    def test_modelformset_factory_labels_overrides(self):
        BookFormSet = modelformset_factory(
            Book, fields="__all__", labels={"title": "Name"}
        )
        form = BookFormSet.form()
        self.assertHTMLEqual(
            form["title"].label_tag(), '<label for="id_title">Name:</label>'
        )
        self.assertHTMLEqual(
            form["title"].legend_tag(),
            '<legend for="id_title">Name:</legend>',
        )

    def test_inlineformset_factory_labels_overrides(self):
        BookFormSet = inlineformset_factory(
            Author, Book, fields="__all__", labels={"title": "Name"}
        )
        form = BookFormSet.form()
        self.assertHTMLEqual(
            form["title"].label_tag(), '<label for="id_title">Name:</label>'
        )
        self.assertHTMLEqual(
            form["title"].legend_tag(),
            '<legend for="id_title">Name:</legend>',
        )

    def test_modelformset_factory_help_text_overrides(self):
        BookFormSet = modelformset_factory(
            Book, fields="__all__", help_texts={"title": "Choose carefully."}
        )
        form = BookFormSet.form()
        self.assertEqual(form["title"].help_text, "Choose carefully.")

    def test_inlineformset_factory_help_text_overrides(self):
        BookFormSet = inlineformset_factory(
            Author, Book, fields="__all__", help_texts={"title": "Choose carefully."}
        )
        form = BookFormSet.form()
        self.assertEqual(form["title"].help_text, "Choose carefully.")

    def test_modelformset_factory_error_messages_overrides(self):
        author = Author.objects.create(pk=1, name="Charles Baudelaire")
        BookFormSet = modelformset_factory(
            Book,
            fields="__all__",
            error_messages={"title": {"max_length": "Title too long!!"}},
        )
        form = BookFormSet.form(data={"title": "Foo " * 30, "author": author.id})
        form.full_clean()
        self.assertEqual(form.errors, {"title": ["Title too long!!"]})

    def test_inlineformset_factory_error_messages_overrides(self):
        author = Author.objects.create(pk=1, name="Charles Baudelaire")
        BookFormSet = inlineformset_factory(
            Author,
            Book,
            fields="__all__",
            error_messages={"title": {"max_length": "Title too long!!"}},
        )
        form = BookFormSet.form(data={"title": "Foo " * 30, "author": author.id})
        form.full_clean()
        self.assertEqual(form.errors, {"title": ["Title too long!!"]})

    def test_modelformset_factory_field_class_overrides(self):
        author = Author.objects.create(pk=1, name="Charles Baudelaire")
        BookFormSet = modelformset_factory(
            Book,
            fields="__all__",
            field_classes={
                "title": forms.SlugField,
            },
        )
        form = BookFormSet.form(data={"title": "Foo " * 30, "author": author.id})
        self.assertIs(Book._meta.get_field("title").__class__, models.CharField)
        self.assertIsInstance(form.fields["title"], forms.SlugField)

    def test_inlineformset_factory_field_class_overrides(self):
        author = Author.objects.create(pk=1, name="Charles Baudelaire")
        BookFormSet = inlineformset_factory(
            Author,
            Book,
            fields="__all__",
            field_classes={
                "title": forms.SlugField,
            },
        )
        form = BookFormSet.form(data={"title": "Foo " * 30, "author": author.id})
        self.assertIs(Book._meta.get_field("title").__class__, models.CharField)
        self.assertIsInstance(form.fields["title"], forms.SlugField)

    def test_modelformset_factory_absolute_max(self):
        AuthorFormSet = modelformset_factory(
            Author, fields="__all__", absolute_max=1500
        )
        data = {
            "form-TOTAL_FORMS": "1501",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "0",
        }
        formset = AuthorFormSet(data=data)
        self.assertIs(formset.is_valid(), False)
        self.assertEqual(len(formset.forms), 1500)
        self.assertEqual(
            formset.non_form_errors(),
            ["Please submit at most 1000 forms."],
        )

    def test_modelformset_factory_absolute_max_with_max_num(self):
        AuthorFormSet = modelformset_factory(
            Author,
            fields="__all__",
            max_num=20,
            absolute_max=100,
        )
        data = {
            "form-TOTAL_FORMS": "101",
            "form-INITIAL_FORMS": "0",
            "form-MAX_NUM_FORMS": "0",
        }
        formset = AuthorFormSet(data=data)
        self.assertIs(formset.is_valid(), False)
        self.assertEqual(len(formset.forms), 100)
        self.assertEqual(
            formset.non_form_errors(),
            ["Please submit at most 20 forms."],
        )

    def test_inlineformset_factory_absolute_max(self):
        author = Author.objects.create(name="Charles Baudelaire")
        BookFormSet = inlineformset_factory(
            Author,
            Book,
            fields="__all__",
            absolute_max=1500,
        )
        data = {
            "book_set-TOTAL_FORMS": "1501",
            "book_set-INITIAL_FORMS": "0",
            "book_set-MAX_NUM_FORMS": "0",
        }
        formset = BookFormSet(data, instance=author)
        self.assertIs(formset.is_valid(), False)
        self.assertEqual(len(formset.forms), 1500)
        self.assertEqual(
            formset.non_form_errors(),
            ["Please submit at most 1000 forms."],
        )

    def test_inlineformset_factory_absolute_max_with_max_num(self):
        author = Author.objects.create(name="Charles Baudelaire")
        BookFormSet = inlineformset_factory(
            Author,
            Book,
            fields="__all__",
            max_num=20,
            absolute_max=100,
        )
        data = {
            "book_set-TOTAL_FORMS": "101",
            "book_set-INITIAL_FORMS": "0",
            "book_set-MAX_NUM_FORMS": "0",
        }
        formset = BookFormSet(data, instance=author)
        self.assertIs(formset.is_valid(), False)
        self.assertEqual(len(formset.forms), 100)
        self.assertEqual(
            formset.non_form_errors(),
            ["Please submit at most 20 forms."],
        )

    def test_modelformset_factory_can_delete_extra(self):
        AuthorFormSet = modelformset_factory(
            Author,
            fields="__all__",
            can_delete=True,
            can_delete_extra=True,
            extra=2,
        )
        formset = AuthorFormSet()
        self.assertEqual(len(formset), 2)
        self.assertIn("DELETE", formset.forms[0].fields)
        self.assertIn("DELETE", formset.forms[1].fields)

    def test_modelformset_factory_disable_delete_extra(self):
        AuthorFormSet = modelformset_factory(
            Author,
            fields="__all__",
            can_delete=True,
            can_delete_extra=False,
            extra=2,
        )
        formset = AuthorFormSet()
        self.assertEqual(len(formset), 2)
        self.assertNotIn("DELETE", formset.forms[0].fields)
        self.assertNotIn("DELETE", formset.forms[1].fields)

    def test_inlineformset_factory_can_delete_extra(self):
        BookFormSet = inlineformset_factory(
            Author,
            Book,
            fields="__all__",
            can_delete=True,
            can_delete_extra=True,
            extra=2,
        )
        formset = BookFormSet()
        self.assertEqual(len(formset), 2)
        self.assertIn("DELETE", formset.forms[0].fields)
        self.assertIn("DELETE", formset.forms[1].fields)

    def test_inlineformset_factory_can_not_delete_extra(self):
        BookFormSet = inlineformset_factory(
            Author,
            Book,
            fields="__all__",
            can_delete=True,
            can_delete_extra=False,
            extra=2,
        )
        formset = BookFormSet()
        self.assertEqual(len(formset), 2)
        self.assertNotIn("DELETE", formset.forms[0].fields)
        self.assertNotIn("DELETE", formset.forms[1].fields)

    def test_inlineformset_factory_passes_renderer(self):
        from django.forms.renderers import Jinja2

        renderer = Jinja2()
        BookFormSet = inlineformset_factory(
            Author,
            Book,
            fields="__all__",
            renderer=renderer,
        )
        formset = BookFormSet()
        self.assertEqual(formset.renderer, renderer)

    def test_modelformset_factory_passes_renderer(self):
        from django.forms.renderers import Jinja2

        renderer = Jinja2()
        BookFormSet = modelformset_factory(Author, fields="__all__", renderer=renderer)
        formset = BookFormSet()
        self.assertEqual(formset.renderer, renderer)

    def test_modelformset_factory_default_renderer(self):
        class CustomRenderer(DjangoTemplates):
            pass

        class ModelFormWithDefaultRenderer(ModelForm):
            default_renderer = CustomRenderer()

        BookFormSet = modelformset_factory(
            Author, form=ModelFormWithDefaultRenderer, fields="__all__"
        )
        formset = BookFormSet()
        self.assertEqual(
            formset.forms[0].renderer, ModelFormWithDefaultRenderer.default_renderer
        )
        self.assertEqual(
            formset.empty_form.renderer, ModelFormWithDefaultRenderer.default_renderer
        )
        self.assertIsInstance(formset.renderer, DjangoTemplates)

    def test_inlineformset_factory_default_renderer(self):
        class CustomRenderer(DjangoTemplates):
            pass

        class ModelFormWithDefaultRenderer(ModelForm):
            default_renderer = CustomRenderer()

        BookFormSet = inlineformset_factory(
            Author,
            Book,
            form=ModelFormWithDefaultRenderer,
            fields="__all__",
        )
        formset = BookFormSet()
        self.assertEqual(
            formset.forms[0].renderer, ModelFormWithDefaultRenderer.default_renderer
        )
        self.assertEqual(
            formset.empty_form.renderer, ModelFormWithDefaultRenderer.default_renderer
        )
        self.assertIsInstance(formset.renderer, DjangoTemplates)
