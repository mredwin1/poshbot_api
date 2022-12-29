from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.db.models.aggregates import Count
from django.utils.html import format_html, urlencode
from django.urls import reverse
from . import models


admin.site.register(models.Offer)
admin.site.register(models.ProxyConnection)


class ListingInline(admin.StackedInline):
    model = models.Listing
    extra = 0


class ListingImageInline(admin.TabularInline):
    model = models.ListingImage
    extra = 0


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
    readonly_fields = ['sales', 'date_added']
    list_display = ['username', 'status', 'associated_campaign', 'email', 'password', 'phone_number']
    search_fields = ['username__istartswith', 'email__istartswith']
    list_filter = ['campaign', PoshUserStatusFilter]
    list_per_page = 20

    def get_queryset(self, request):
        return super(PoshUserAdmin, self).get_queryset(request).select_related('campaign')

    @admin.display(ordering='campaign')
    def associated_campaign(self, posh_user):
        if posh_user.campaign:
            url = f"{reverse('admin:core_campaign_changelist')}?{urlencode({'id': str(posh_user.campaign.id)})}"
            return format_html('<a href="{}">{}</a>', url, posh_user.campaign)
        return posh_user.campaign

    fieldsets = (
        ('Important Information', {
            'fields': (
                ('is_active', 'is_registered', 'profile_updated'),
                ('user',),
                ('date_added', 'sales'),
                ('username', 'password', 'email'),
                ('phone_number'),
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
    list_display = ['title', 'associated_campaign']
    search_fields = ['title__istartswith']
    list_filter = ['campaign']
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
    readonly_fields = ['status']
    list_display = ['title', 'status', 'associated_posh_user', 'listings_count']
    search_fields = ['title__istartswith']
    list_filter = ['status', 'posh_user']
    inlines = [ListingInline]

    def get_queryset(self, request):
        return super(CampaignAdmin, self).get_queryset(request).select_related('posh_user').annotate(listings_count=Count('listings'))

    @admin.display(ordering='posh_user')
    def associated_posh_user(self, campaign):
        if campaign.posh_user:
            url = f"{reverse('admin:core_poshuser_changelist')}?{urlencode({'id': str(campaign.posh_user.id)})}"
            return format_html('<a href="{}">{}</a>', url, campaign.posh_user)
        return campaign.posh_user

    @admin.display(ordering='listings_count')
    def listings_count(self, campaign):
        url = f"{reverse('admin:core_listing_changelist')}?{urlencode({'campaign__id': str(campaign.id)})}"
        return format_html('<a href="{}">{}</a>', url, campaign.listings_count)

    fieldsets = (
        ('Campaign Information', {
            'fields': (
                ('auto_run', 'generate_users'),
                ('user',),
                ('status',),
                ('posh_user',),
                ('mode',),
                ('title', 'delay', 'lowest_price'),
            )
        }),
    )
