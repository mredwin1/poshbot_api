import datetime
import pytz

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models.aggregates import Count
from django.utils.html import format_html, urlencode
from django.urls import reverse
from . import models


admin.site.register(models.Offer)
admin.site.register(models.Device)


@admin.action(description='Start selected campaigns')
def start_campaigns(modeladmin, request, queryset):
    queryset.update(status=models.Campaign.STARTING, next_runtime=datetime.datetime.utcnow().replace(tzinfo=pytz.utc))


@admin.action(description='Stop selected campaigns')
def start_campaigns(modeladmin, request, queryset):
    queryset.update(status=models.Campaign.STOPPING)


class ListingInline(admin.StackedInline):
    model = models.Listing
    extra = 0


class ListingImageInline(admin.TabularInline):
    model = models.ListingImage
    extra = 0


class LogEntryInline(admin.StackedInline):
    model = models.LogEntry
    extra = 0
    fields = ['level', 'timestamp_seconds', 'message', 'image']
    readonly_fields = ['level', 'timestamp_seconds', 'message', 'image']
    ordering = ['timestamp']

    @staticmethod
    def timestamp_seconds(log_entry):
        return log_entry.timestamp.strftime('%b %d, %Y, %I:%M:%S %p')


class PoshUserStatusFilter(admin.SimpleListFilter):
    title = 'status'
    parameter_name = 'status'

    def lookups(self, request, model_admin):
        return (
            ('unassigned', 'Unassigned'),
            ('assigned', 'Assigned'),
            ('running', 'Running')
        )

    def queryset(self, request, queryset):
        value = self.value()

        if value == 'unassigned':
            return queryset.filter(campaign__isnull=True)
        elif value == 'assigned':
            return queryset.filter(campaign__status=models.Campaign.IDLE)
        elif value == 'running':
            return queryset.filter(campaign__status=models.Campaign.RUNNING)

        return queryset


@admin.register(models.User)
class UserAdmin(BaseUserAdmin):
    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': ('username', 'password1', 'password2', 'email', 'first_name', 'last_name'),
            },
        ),
    )


@admin.register(models.PoshUser)
class PoshUserAdmin(admin.ModelAdmin):
    readonly_fields = ['sales', 'date_added', 'time_to_install_clone', 'time_to_register', 'time_to_finish_registration']
    list_display = ['username', 'status', 'associated_user', 'associated_campaign', 'email']
    search_fields = ['username__istartswith', 'email__istartswith']
    list_filter = ['user', PoshUserStatusFilter]
    list_per_page = 20

    def get_queryset(self, request):
        return super(PoshUserAdmin, self).get_queryset(request).select_related('campaign')

    @admin.display(ordering='campaign')
    def associated_campaign(self, posh_user):
        if posh_user.campaign:
            url = f"{reverse('admin:core_campaign_changelist')}?{urlencode({'id': str(posh_user.campaign.id)})}"
            return format_html('<a href="{}">{}</a>', url, posh_user.campaign)
        return posh_user.campaign

    @admin.display(ordering='user')
    def associated_user(self, posh_user):
        url = f"{reverse('admin:core_user_changelist')}?{urlencode({'id': str(posh_user.user.id)})}"
        return format_html('<a href="{}">{}</a>', url, posh_user.user)

    fieldsets = (
        ('Important Information', {
            'fields': (
                ('is_active', 'clone_installed', 'is_registered', 'finished_registration', 'profile_updated'),
                ('time_to_install_clone', 'time_to_register', 'time_to_finish_registration'),
                ('user', 'app_package'),
                ('date_added', 'sales'),
                ('username', 'password', 'email'),
                ('phone_number',)
            )
        }),
        ('Other Information', {
            'classes': ('collapse',),
            'fields': (
                ('first_name', 'last_name'),
                ('date_of_birth', 'gender'),
                ('profile_picture', 'profile_picture_id'),
                ('header_picture')
            )
        }),
    )


@admin.register(models.Listing)
class ListingAdmin(admin.ModelAdmin):
    autocomplete_fields = ['campaign']
    list_display = ['title', 'associated_user', 'associated_campaign']
    search_fields = ['title__istartswith']
    list_filter = ['user', 'campaign']
    list_per_page = 20
    inlines = [ListingImageInline]

    def get_queryset(self, request):
        return super(ListingAdmin, self).get_queryset(request).select_related('campaign')

    @admin.display(ordering='campaign')
    def associated_campaign(self, listing):
        if listing.campaign:
            url = f"{reverse('admin:core_campaign_changelist')}?{urlencode({'id': str(listing.campaign.id)})}"
            return format_html('<a href="{}">{}</a>', url, listing.campaign)
        return listing.campaign

    @admin.display(ordering='user')
    def associated_user(self, listing):
        if listing.user:
            url = f"{reverse('admin:core_user_changelist')}?{urlencode({'id': str(listing.user.id)})}"
            return format_html('<a href="{}">{}</a>', url, listing.user)
        return listing.user

    fieldsets = (
        ('Listing Information', {
            'fields': (
                ('user', 'campaign'),
                ('title',),
                ('size', 'brand'),
                ('category', 'subcategory'),
                ('original_price', 'listing_price', 'lowest_price'),
                ('description',),
                ('cover_photo',),
            )
        }),
    )


@admin.register(models.Campaign)
class CampaignAdmin(admin.ModelAdmin):
    autocomplete_fields = ['posh_user']
    list_display = ['title', 'status', 'queue_status','associated_user', 'associated_posh_user', 'listings_count']
    search_fields = ['title__istartswith', 'posh_user__username__istartswith']
    list_filter = ['status', 'user']
    inlines = [ListingInline]

    def get_queryset(self, request):
        return super(CampaignAdmin, self).get_queryset(request).select_related('posh_user').annotate(listings_count=Count('listings'))

    @admin.display(ordering='posh_user')
    def associated_posh_user(self, campaign):
        if campaign.posh_user:
            url = f"{reverse('admin:core_poshuser_changelist')}?{urlencode({'id': str(campaign.posh_user.id)})}"
            return format_html('<a href="{}">{}</a>', url, campaign.posh_user)
        return campaign.posh_user

    @admin.display(ordering='user')
    def associated_user(self, campaign):
        url = f"{reverse('admin:core_user_changelist')}?{urlencode({'id': str(campaign.user.id)})}"
        return format_html('<a href="{}">{}</a>', url, campaign.user)

    @admin.display(ordering='listings_count')
    def listings_count(self, campaign):
        url = f"{reverse('admin:core_listing_changelist')}?{urlencode({'campaign__id': str(campaign.id)})}"
        return format_html('<a href="{}">{}</a>', url, campaign.listings_count)

    fieldsets = (
        ('Campaign Information', {
            'fields': (
                ('auto_run', 'generate_users'),
                ('user',),
                ('status', 'queue_status', 'next_runtime'),
                ('posh_user',),
                ('mode',),
                ('title', 'delay', 'lowest_price'),
            )
        }),
    )


@admin.register(models.LogGroup)
class LogGroupAdmin(admin.ModelAdmin):
    list_display = ['created_date', 'campaign', 'posh_user']
    readonly_fields = ['campaign', 'posh_user', 'created_date']
    list_filter = ['posh_user', 'campaign', 'created_date']
    inlines = [LogEntryInline]

    def get_queryset(self, request):
        return super(LogGroupAdmin, self).get_queryset(request)

    fieldsets = (
        ('Log Information', {
            'fields': (
                ('created_date',),
                ('campaign', 'posh_user'),
            )
        }),
    )


@admin.register(models.ListedItem)
class ListedItemAdmin(admin.ModelAdmin):
    readonly_fields = ['time_to_list']
    autocomplete_fields = ['posh_user']
    list_display = ['listing_title', 'status', 'associated_user', 'associated_posh_user']
    search_fields = ['listing_title__istartswith', 'posh_user__username__istartswith']
    list_filter = ['status', 'posh_user__user', 'posh_user']

    def get_queryset(self, request):
        return super(ListedItemAdmin, self).get_queryset(request).select_related('posh_user')

    @admin.display(ordering='posh_user')
    def associated_posh_user(self, listed_item):
        url = f"{reverse('admin:core_poshuser_changelist')}?{urlencode({'id': str(listed_item.posh_user.id)})}"
        return format_html('<a href="{}">{}</a>', url, listed_item.posh_user)

    @admin.display(ordering='posh_user__user')
    def associated_user(self, listed_item):
        url = f"{reverse('admin:core_user_changelist')}?{urlencode({'id': str(listed_item.posh_user.user.id)})}"
        return format_html('<a href="{}">{}</a>', url, listed_item.posh_user.user)

    fieldsets = (
        ('Campaign Information', {
            'fields': (
                ('posh_user', 'listing'),
                ('listing_title', 'status', 'time_to_list'),
                ('datetime_listed', 'datetime_passed_review'),
                ('datetime_removed', 'datetime_sold'),
            )
        }),
    )
