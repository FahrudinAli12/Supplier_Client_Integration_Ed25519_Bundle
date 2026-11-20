/**
 * RFID Linen Pro — Manajemen Linen Page
 *
 * Search, filter, pagination, and CRUD for individual linen items with RFID EPC tags.
 * Uses Alpine.js x-data component for reactive state.
 */

import { api } from '../api.js';
import { showSuccessToast } from '../shell.js';

export const manajemenLinenPage = {
    render() {
        return `
<div x-data="manajemenLinenData()" x-init="initPage()">
    <!-- Glass Panel Container -->
    <div class="glass-panel rounded-2xl border border-glass-border shadow-sm w-full overflow-hidden flex flex-col">
        <!-- Header Controls -->
        <div class="p-6 flex flex-col lg:flex-row justify-between items-start lg:items-center gap-4 border-b border-glass-border">
            <div>
                <h1 class="font-headline-lg font-bold text-primary text-2xl">Manajemen Linen</h1>
                <p class="font-body-md text-on-surface-variant">Daftar seluruh item linen terdaftar, status keberadaan, dan Tag EPC RFID.</p>
            </div>
            <button @click="openAddModal()" class="bg-primary hover:bg-primary/90 text-on-primary font-label-lg px-5 py-2.5 rounded-full shadow-md transition-all flex items-center gap-2 shrink-0">
                <span class="material-symbols-outlined text-[20px]">add</span>
                Tambah Linen Baru
            </button>
        </div>

        <!-- Filter & Search Bar -->
        <div class="px-6 py-4 bg-white/30 border-b border-glass-border flex flex-col md:flex-row items-stretch md:items-center justify-between gap-4">
            <!-- Search Input -->
            <div class="relative flex-1 max-w-md">
                <span class="material-symbols-outlined absolute left-3.5 top-1/2 -translate-y-1/2 text-on-surface-variant text-[20px]">search</span>
                <input type="text" x-model="search" @input="onSearchInput()" placeholder="Cari berdasarkan EPC, nama linen, atau ID..."
                       class="w-full bg-white/70 border border-glass-border rounded-xl pl-10 pr-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50 text-on-surface" />
            </div>

            <!-- Filters -->
            <div class="flex flex-wrap items-center gap-3">
                <!-- Filter Kategori -->
                <div class="flex items-center gap-2">
                    <label class="font-label-md text-on-surface shrink-0">Kategori:</label>
                    <select x-model="filterKategori" @change="onKategoriChange()"
                            class="bg-white/70 border border-glass-border rounded-xl px-3 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50 text-on-surface text-sm">
                        <option value="">Semua Kategori</option>
                        <template x-for="kat in kategoriList" :key="kat.kategori_id">
                            <option :value="kat.kategori_id" x-text="kat.nama"></option>
                        </template>
                    </select>
                </div>

                <!-- Filter Status -->
                <div class="flex items-center gap-2">
                    <label class="font-label-md text-on-surface shrink-0">Status:</label>
                    <select x-model="filterStatus" @change="onStatusChange()"
                            class="bg-white/70 border border-glass-border rounded-xl px-3 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50 text-on-surface text-sm">
                        <option value="">Semua Status</option>
                        <option value="tersedia">Tersedia</option>
                        <option value="dikirim">Dikirim</option>
                    </select>
                </div>
            </div>
        </div>

        <!-- Table -->
        <div class="overflow-x-auto">
            <table class="w-full text-left border-collapse">
                <thead>
                    <tr class="bg-white/40 text-on-surface-variant font-label-md border-b border-glass-border">
                        <th class="py-3 px-6">Tag EPC (RFID)</th>
                        <th class="py-3 px-6">Nama Linen</th>
                        <th class="py-3 px-6">Kategori</th>
                        <th class="py-3 px-6">Status</th>
                        <th class="py-3 px-6">Tanggal Terdaftar</th>
                        <th class="py-3 px-6 text-right">Aksi</th>
                    </tr>
                </thead>
                <tbody>
                    <!-- Loading State -->
                    <template x-if="loading">
                        <tr>
                            <td colspan="6" class="py-8 text-center text-on-surface-variant">
                                <div class="flex items-center justify-center gap-3">
                                    <div class="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                                    Memuat data linen...
                                </div>
                            </td>
                        </tr>
                    </template>

                    <!-- Empty State -->
                    <template x-if="!loading && items.length === 0">
                        <tr>
                            <td colspan="6" class="py-8 text-center text-on-surface-variant">
                                Tidak ada data linen yang sesuai pencarian/filter.
                            </td>
                        </tr>
                    </template>

                    <!-- Data Rows -->
                    <template x-for="item in items" :key="item.epc">
                        <tr class="border-b border-glass-border/50 hover:bg-white/20 transition-colors">
                            <td class="py-3.5 px-6 font-data-mono font-bold text-primary" x-text="item.epc"></td>
                            <td class="py-3.5 px-6 font-body-md font-semibold" x-text="item.nama_linen || item.nama || '-'"></td>
                            <td class="py-3.5 px-6 font-body-md">
                                <span class="inline-block px-3 py-1 bg-primary/10 text-primary font-bold rounded-full text-label-sm"
                                      x-text="item.kategori || item.nama_kategori || '-'"></span>
                            </td>
                            <td class="py-3.5 px-6 font-body-md">
                                <template x-if="(item.status || '').toLowerCase() === 'tersedia'">
                                    <span class="inline-flex items-center gap-1.5 px-3 py-1 bg-status-success/10 text-status-success font-bold rounded-full text-label-sm">
                                        <span class="w-2 h-2 rounded-full bg-status-success"></span>
                                        Tersedia
                                    </span>
                                </template>
                                <template x-if="(item.status || '').toLowerCase() === 'dikirim'">
                                    <span class="inline-flex items-center gap-1.5 px-3 py-1 bg-primary-container/10 text-primary-container font-bold rounded-full text-label-sm">
                                        <span class="w-2 h-2 rounded-full bg-primary-container"></span>
                                        Dikirim
                                    </span>
                                </template>
                                <template x-if="(item.status || '').toLowerCase() !== 'tersedia' && (item.status || '').toLowerCase() !== 'dikirim'">
                                    <span class="inline-flex items-center gap-1.5 px-3 py-1 bg-gray-200 text-gray-700 font-bold rounded-full text-label-sm" x-text="item.status"></span>
                                </template>
                            </td>
                            <td class="py-3.5 px-6 font-body-md text-on-surface-variant" x-text="formatDate(item.created_at || item.created_at_str || item.timestamp)"></td>
                            <td class="py-3.5 px-6 text-right">
                                <button @click="openDetailModal(item)" class="text-secondary hover:underline font-label-md mr-3">Detail</button>
                                <button @click="openEditModal(item)" class="text-primary hover:underline font-label-md mr-3">Edit</button>
                                <button @click="confirmDelete(item)" class="text-status-error hover:underline font-label-md">Hapus</button>
                            </td>
                        </tr>
                    </template>
                </tbody>
            </table>
        </div>

        <!-- Pagination Controls -->
        <div class="p-4 bg-white/20 border-t border-glass-border flex flex-col sm:flex-row items-center justify-between gap-4 font-label-md text-on-surface-variant">
            <div>
                Menampilkan <span class="font-bold text-on-surface" x-text="items.length"></span> dari <span class="font-bold text-on-surface" x-text="total_data"></span> item linen
            </div>
            <div class="flex items-center gap-2">
                <button @click="goToPage(page - 1)" :disabled="page <= 1"
                        class="px-3.5 py-1.5 rounded-lg border border-glass-border bg-white/50 hover:bg-white disabled:opacity-40 disabled:pointer-events-none transition-all flex items-center gap-1">
                    <span class="material-symbols-outlined text-[18px]">chevron_left</span>
                    Prev
                </button>

                <span class="px-3 py-1 bg-primary text-on-primary rounded-lg font-bold" x-text="page + ' / ' + total_page"></span>

                <button @click="goToPage(page + 1)" :disabled="page >= total_page"
                        class="px-3.5 py-1.5 rounded-lg border border-glass-border bg-white/50 hover:bg-white disabled:opacity-40 disabled:pointer-events-none transition-all flex items-center gap-1">
                    Next
                    <span class="material-symbols-outlined text-[18px]">chevron_right</span>
                </button>
            </div>
        </div>

        <!-- Error State -->
        <template x-if="fetchError">
            <div class="p-6 text-center text-status-error font-body-md" x-text="'Error: ' + fetchError"></div>
        </template>
    </div>

    <!-- ═══ Modal Form (Tambah / Edit) ═══ -->
    <div x-show="showModal"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="fixed inset-0 z-[150] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
         style="display: none;"
         @keydown.escape.window="closeModal()">
        <div @click.outside="closeModal()"
             x-transition:enter="transition ease-out duration-200"
             x-transition:enter-start="opacity-0 scale-95"
             x-transition:enter-end="opacity-100 scale-100"
             class="bg-surface/90 backdrop-blur-2xl border border-glass-border rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4">
            <h2 class="font-headline-md font-bold text-primary" x-text="editMode ? 'Edit Linen' : 'Tambah Linen Baru'"></h2>
            <form @submit.prevent="handleSubmit()" class="flex flex-col gap-4">
                <!-- Tag EPC (RFID) -->
                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-on-surface">Tag EPC (RFID) <span class="text-status-error">*</span></label>
                    <input x-model="form.epc" type="text" required :readonly="editMode" placeholder="e.g. E2801191A0000001"
                           :class="editMode ? 'bg-black/10 cursor-not-allowed text-on-surface-variant' : 'bg-white/60 focus:ring-2 focus:ring-primary/50'"
                           class="border border-glass-border rounded-xl px-4 py-2 font-data-mono font-bold focus:outline-none" />
                </div>

                <!-- Dependent Dropdown: Kategori Linen -->
                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-on-surface">Kategori Linen <span class="text-status-error">*</span></label>
                    <select x-model="form.kategori_id" @change="onFormKategoriChange()" required
                            class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50 text-on-surface">
                        <option value="" disabled>-- Pilih Kategori --</option>
                        <template x-for="kat in kategoriList" :key="kat.kategori_id">
                            <option :value="kat.kategori_id" x-text="kat.nama"></option>
                        </template>
                    </select>
                </div>

                <!-- Dependent Dropdown: Nama Linen -->
                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-on-surface">Nama Linen <span class="text-status-error">*</span></label>
                    <select x-model="form.nama_linen_id" required :disabled="loadingNamaLinen || namaLinenOptions.length === 0"
                            class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50 text-on-surface disabled:opacity-50">
                        <option value="" disabled>-- Pilih Nama Linen --</option>
                        <template x-for="nl in namaLinenOptions" :key="nl.nama_linen_id">
                            <option :value="nl.nama_linen_id" x-text="nl.nama"></option>
                        </template>
                    </select>
                </div>

                <!-- Status Linen -->
                <div class="flex flex-col gap-1">
                    <label class="font-label-md text-on-surface">Status Linen</label>
                    <select x-model="form.status" required
                            class="bg-white/60 border border-glass-border rounded-xl px-4 py-2 text-body-md focus:outline-none focus:ring-2 focus:ring-primary/50 text-on-surface">
                        <option value="tersedia">Tersedia</option>
                        <option value="dikirim">Dikirim</option>
                    </select>
                </div>

                <div class="flex justify-end gap-3 mt-4">
                    <button type="button" @click="closeModal()" class="px-5 py-2 rounded-full border border-glass-border text-label-lg hover:bg-white/50 transition-colors">Batal</button>
                    <button type="submit" class="bg-primary text-on-primary px-6 py-2 rounded-full font-label-lg shadow-md hover:bg-primary/90 transition-colors"
                            :disabled="submitting">
                        <span x-show="!submitting">Simpan</span>
                        <span x-show="submitting" class="flex items-center gap-2">
                            <span class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>
                            Menyimpan...
                        </span>
                    </button>
                </div>
            </form>
        </div>
    </div>

    <!-- ═══ Modal Konfirmasi Hapus ═══ -->
    <div x-show="showDeleteConfirm"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="fixed inset-0 z-[150] bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
         style="display: none;"
         @keydown.escape.window="showDeleteConfirm = false">
        <div @click.outside="showDeleteConfirm = false"
             class="bg-surface/90 backdrop-blur-2xl border border-glass-border rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4">
            <div class="flex items-center gap-3 text-status-error">
                <span class="material-symbols-outlined text-[28px]">warning</span>
                <h3 class="font-headline-md font-bold">Hapus Item Linen?</h3>
            </div>
            <p class="font-body-md text-on-surface-variant">
                Apakah Anda yakin ingin menghapus item linen dengan EPC
                <strong class="text-on-surface font-data-mono" x-text="deleteTarget?.epc"></strong>?
                Tindakan ini tidak dapat dibatalkan.
            </p>
            <div class="flex justify-end gap-3 mt-2">
                <button @click="showDeleteConfirm = false" class="px-5 py-2 rounded-full border border-glass-border text-label-lg hover:bg-white/50 transition-colors">Batal</button>
                <button @click="executeDelete()" class="bg-status-error text-white px-6 py-2 rounded-full font-label-lg shadow-md hover:bg-status-error/90 transition-colors"
                        :disabled="submitting">
                    Hapus
                </button>
            </div>
        </div>
    </div>

    <!-- ═══ Modal Detail Linen & Riwayat Pengiriman ═══ -->
    <div x-show="detailModal.show"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="fixed inset-0 z-[160] bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
         style="display: none;"
         @keydown.escape.window="detailModal.show = false">
        <div @click.outside="detailModal.show = false"
             x-transition:enter="transition ease-out duration-200"
             x-transition:enter-start="opacity-0 scale-95"
             x-transition:enter-end="opacity-100 scale-100"
             class="bg-surface/95 backdrop-blur-2xl border border-glass-border rounded-2xl p-6 max-w-2xl w-full shadow-2xl flex flex-col gap-4 max-h-[90vh] overflow-y-auto">
            <div class="flex justify-between items-center border-b border-glass-border pb-4">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-full bg-primary/10 text-primary flex items-center justify-center">
                        <span class="material-symbols-outlined text-[24px]">info</span>
                    </div>
                    <div>
                        <h2 class="font-headline-md font-bold text-primary text-xl">Detail & Riwayat Linen</h2>
                        <span class="font-data-mono text-xs font-bold text-on-surface-variant" x-text="detailModal.data?.epc"></span>
                    </div>
                </div>
                <button @click="detailModal.show = false" class="text-on-surface-variant hover:text-on-surface text-2xl font-bold">&times;</button>
            </div>

            <template x-if="detailModal.loading">
                <div class="py-12 text-center text-on-surface-variant flex items-center justify-center gap-3">
                    <div class="w-5 h-5 border-2 border-primary border-t-transparent rounded-full animate-spin"></div>
                    Memuat rincian dan riwayat linen...
                </div>
            </template>

            <template x-if="!detailModal.loading && detailModal.data">
                <div class="flex flex-col gap-5">
                    <!-- Info Summary Grid -->
                    <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-white/40 p-4 rounded-xl border border-glass-border">
                        <div>
                            <span class="text-label-sm font-semibold text-on-surface-variant block">Nama Linen:</span>
                            <span class="font-body-md font-bold text-on-surface" x-text="detailModal.data.nama_linen || detailModal.data.nama || '-'"></span>
                        </div>
                        <div>
                            <span class="text-label-sm font-semibold text-on-surface-variant block">Kategori:</span>
                            <span class="font-body-md font-bold text-on-surface" x-text="detailModal.data.kategori || detailModal.data.nama_kategori || '-'"></span>
                        </div>
                        <div>
                            <span class="text-label-sm font-semibold text-on-surface-variant block">Status:</span>
                            <span class="inline-block px-2.5 py-0.5 rounded-full text-xs font-bold capitalize mt-0.5"
                                  :class="(detailModal.data.status || '').toLowerCase() === 'tersedia' ? 'bg-status-success/10 text-status-success' : 'bg-primary-container/10 text-primary-container'"
                                  x-text="detailModal.data.status"></span>
                        </div>
                        <div>
                            <span class="text-label-sm font-semibold text-on-surface-variant block">Tgl Registrasi:</span>
                            <span class="font-body-md text-xs font-bold text-on-surface" x-text="formatDate(detailModal.data.tanggal_registrasi || detailModal.data.created_at || detailModal.data.timestamp)"></span>
                        </div>
                    </div>

                    <!-- Rumah Sakit Terkait / Transaksi Terakhir -->
                    <div class="bg-white/40 p-4 rounded-xl border border-glass-border" x-show="detailModal.data.transaksi_terakhir">
                        <h4 class="font-label-md font-bold text-on-surface mb-2">Transaksi Terakhir</h4>
                        <div class="grid grid-cols-2 sm:grid-cols-3 gap-2 text-sm">
                            <div>
                                <span class="text-xs text-on-surface-variant block">RS Tujuan:</span>
                                <span class="font-bold text-on-surface" x-text="detailModal.data.transaksi_terakhir?.nama_rs || '-'"></span>
                            </div>
                            <div>
                                <span class="text-xs text-on-surface-variant block">Kode Verifikasi:</span>
                                <span class="font-data-mono font-bold text-primary" x-text="detailModal.data.transaksi_terakhir?.kode_verifikasi || '-'"></span>
                            </div>
                            <div>
                                <span class="text-xs text-on-surface-variant block">Waktu Pengiriman:</span>
                                <span class="text-xs font-semibold text-on-surface" x-text="formatDate(detailModal.data.transaksi_terakhir?.waktu)"></span>
                            </div>
                        </div>
                    </div>

                    <!-- Riwayat Pengiriman Table -->
                    <div>
                        <h3 class="font-headline-md font-bold text-on-surface text-base mb-2">Riwayat Pengiriman & Perubahan Status</h3>
                        <div class="overflow-x-auto rounded-xl border border-glass-border">
                            <table class="w-full text-left border-collapse text-sm">
                                <thead>
                                    <tr class="bg-white/60 text-on-surface-variant font-label-md border-b border-glass-border text-xs">
                                        <th class="py-2.5 px-4">Waktu</th>
                                        <th class="py-2.5 px-4">Rumah Sakit Tujuan</th>
                                        <th class="py-2.5 px-4">Kode Verifikasi</th>
                                        <th class="py-2.5 px-4">Status Sync</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    <template x-if="!detailModal.data.riwayat_pengiriman || detailModal.data.riwayat_pengiriman.length === 0">
                                        <tr>
                                            <td colspan="4" class="py-6 text-center text-on-surface-variant text-xs">
                                                Linen ini belum pernah dikirim dalam transaksi pengiriman apa pun.
                                            </td>
                                        </tr>
                                    </template>
                                    <template x-for="r in (detailModal.data.riwayat_pengiriman || [])" :key="r.kode_verifikasi + r.waktu">
                                        <tr class="border-b border-glass-border/30 hover:bg-white/20">
                                            <td class="py-2.5 px-4 text-xs font-semibold text-on-surface-variant" x-text="formatDate(r.waktu)"></td>
                                            <td class="py-2.5 px-4 font-semibold text-on-surface" x-text="r.nama_rs || '-'"></td>
                                            <td class="py-2.5 px-4 font-data-mono font-bold text-primary text-xs" x-text="r.kode_verifikasi"></td>
                                            <td class="py-2.5 px-4">
                                                <span class="inline-block px-2.5 py-0.5 rounded-full text-xs font-bold"
                                                      :class="r.status_sync === 'sukses' ? 'bg-status-success/10 text-status-success' : 'bg-status-warning/10 text-status-warning'"
                                                      x-text="r.status_sync === 'sukses' ? 'Tersinkronisasi' : r.status_sync"></span>
                                            </td>
                                        </tr>
                                    </template>
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            </template>

            <div class="flex justify-end mt-2">
                <button @click="detailModal.show = false" class="bg-primary text-on-primary font-label-lg px-6 py-2 rounded-full hover:bg-primary/90 transition-colors">Tutup</button>
            </div>
        </div>
    </div>

    <!-- ═══ Modal Error (e.g. 409 conflict) ═══ -->
    <div x-show="errorModal.show"
         x-transition:enter="transition ease-out duration-200"
         x-transition:enter-start="opacity-0"
         x-transition:enter-end="opacity-100"
         x-transition:leave="transition ease-in duration-150"
         x-transition:leave-start="opacity-100"
         x-transition:leave-end="opacity-0"
         class="fixed inset-0 z-[200] bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
         style="display: none;">
        <div class="bg-surface/90 backdrop-blur-2xl border border-glass-border rounded-2xl p-6 max-w-md w-full shadow-2xl flex flex-col gap-4 text-on-surface">
            <div class="flex items-center gap-3 text-status-error">
                <span class="material-symbols-outlined text-[28px]">error</span>
                <h3 class="font-headline-md font-bold" x-text="errorModal.title"></h3>
            </div>
            <p class="font-body-md text-on-surface-variant" x-text="errorModal.message"></p>
            <div class="flex justify-end mt-2">
                <button @click="errorModal.show = false" class="bg-primary text-on-primary font-label-lg px-6 py-2 rounded-full hover:bg-primary/90 transition-colors">Tutup</button>
            </div>
        </div>
    </div>
</div>
        `;
    },

    mount() { },
    unmount() { },
};

export function registerManajemenLinenComponent() {
    if (window.Alpine && !window._manajemenLinenRegistered) {
        window.Alpine.data('manajemenLinenData', () => ({
            items: [],
            total_data: 0,
            total_page: 1,
            page: 1,
            limit: 50,
            search: '',
            filterStatus: '',
            filterKategori: '',
            kategoriList: [],
            namaLinenOptions: [],
            loadingNamaLinen: false,
            loading: true,
            fetchError: null,
            searchTimer: null,

            showModal: false,
            showDeleteConfirm: false,
            editMode: false,
            submitting: false,
            form: { epc: '', kategori_id: '', nama_linen_id: '', status: 'tersedia' },
            editEpc: null,
            deleteTarget: null,
            detailModal: { show: false, loading: false, data: null },
            errorModal: { show: false, title: '', message: '' },

            async initPage() {
                this.fetchKategoriList();
                await this.fetchList();
            },

            async fetchKategoriList() {
                try {
                    const resp = await api.getKategoriList();
                    if (resp.ok) this.kategoriList = resp.data || [];
                } catch (e) {
                    console.error('Error fetching kategori list:', e);
                }
            },

            async fetchList() {
                this.loading = true;
                this.fetchError = null;
                try {
                    const resp = await api.getLinenList(this.page, this.limit, this.search.trim(), this.filterStatus, this.filterKategori);
                    if (!resp.ok) throw new Error(resp.data?.detail || 'Gagal mengambil data linen');

                    const resData = resp.data || {};
                    this.items = resData.data || [];
                    this.total_data = resData.total_data || 0;
                    this.total_page = resData.total_page || 1;
                } catch (err) {
                    console.error(err);
                    this.fetchError = err.message;
                } finally {
                    this.loading = false;
                }
            },

            onSearchInput() {
                if (this.searchTimer) clearTimeout(this.searchTimer);
                this.searchTimer = setTimeout(() => {
                    this.page = 1;
                    this.fetchList();
                }, 350);
            },

            onStatusChange() {
                this.page = 1;
                this.fetchList();
            },

            onKategoriChange() {
                this.page = 1;
                this.fetchList();
            },

            async openDetailModal(item) {
                this.detailModal = { show: true, loading: true, data: item };
                try {
                    const resp = await api.getLinenByEpc(item.epc);
                    if (resp.ok && resp.data) {
                        this.detailModal.data = resp.data;
                    }
                } catch (e) {
                    console.error('Error fetching linen detail:', e);
                } finally {
                    this.detailModal.loading = false;
                }
            },

            goToPage(p) {
                if (p < 1 || p > this.total_page) return;
                this.page = p;
                this.fetchList();
            },

            async onFormKategoriChange() {
                if (!this.form.kategori_id) {
                    this.namaLinenOptions = [];
                    this.form.nama_linen_id = '';
                    return;
                }

                this.loadingNamaLinen = true;
                try {
                    const katId = parseInt(this.form.kategori_id, 10);
                    const resp = await api.getNamaLinenList(katId);
                    if (resp.ok) {
                        this.namaLinenOptions = resp.data || [];
                        // Check if current nama_linen_id is still in options
                        const exists = this.namaLinenOptions.some(nl => nl.nama_linen_id === parseInt(this.form.nama_linen_id, 10));
                        if (!exists) {
                            this.form.nama_linen_id = '';
                        }
                    }
                } catch (e) {
                    console.error('Error fetching dependent nama linen:', e);
                } finally {
                    this.loadingNamaLinen = false;
                }
            },

            async openAddModal() {
                this.editMode = false;
                this.editEpc = null;
                this.form = { epc: '', kategori_id: '', nama_linen_id: '', status: 'tersedia' };
                this.namaLinenOptions = [];
                this.showModal = true;
            },

            async openEditModal(item) {
                this.editMode = true;
                this.editEpc = item.epc;
                this.form = {
                    epc: item.epc,
                    kategori_id: item.kategori_id || '',
                    nama_linen_id: item.nama_linen_id || '',
                    status: (item.status || 'tersedia').toLowerCase(),
                };

                this.showModal = true;

                // Load dependent nama linen options if kategori_id is set
                if (item.kategori_id) {
                    await this.onFormKategoriChange();
                    this.form.nama_linen_id = item.nama_linen_id || '';
                }
            },

            closeModal() {
                this.showModal = false;
            },

            async handleSubmit() {
                this.submitting = true;
                const payload = {
                    nama_linen_id: parseInt(this.form.nama_linen_id, 10),
                    status: this.form.status,
                };

                try {
                    let resp;
                    if (this.editMode) {
                        resp = await api.updateLinen(this.editEpc, payload);
                    } else {
                        resp = await api.createLinen({
                            epc: this.form.epc.trim(),
                            ...payload,
                        });
                    }

                    if (!resp.ok) {
                        this.errorModal = {
                            show: true,
                            title: 'Gagal Menyimpan Linen',
                            message: resp.data?.detail || 'Terjadi kesalahan.',
                        };
                        return;
                    }

                    showSuccessToast(this.editMode ? 'Data Linen berhasil diperbarui!' : 'Linen baru berhasil didaftarkan!');
                    this.closeModal();
                    await this.fetchList();
                } catch (e) {
                    this.errorModal = {
                        show: true,
                        title: 'Error',
                        message: 'Gagal menghubungi server.',
                    };
                } finally {
                    this.submitting = false;
                }
            },

            confirmDelete(item) {
                this.deleteTarget = item;
                this.showDeleteConfirm = true;
            },

            async executeDelete() {
                if (!this.deleteTarget) return;
                this.submitting = true;

                try {
                    const resp = await api.deleteLinen(this.deleteTarget.epc);
                    if (!resp.ok) {
                        this.showDeleteConfirm = false;
                        this.errorModal = {
                            show: true,
                            title: 'Gagal Menghapus Linen',
                            message: resp.data?.detail || 'Item linen tidak dapat dihapus.',
                        };
                        return;
                    }

                    showSuccessToast('Linen berhasil dihapus.');
                    this.showDeleteConfirm = false;
                    this.deleteTarget = null;
                    await this.fetchList();
                } catch (e) {
                    this.showDeleteConfirm = false;
                    this.errorModal = {
                        show: true,
                        title: 'Error',
                        message: 'Gagal menghubungi server.',
                    };
                } finally {
                    this.submitting = false;
                }
            },

            formatDate(isoStr) {
                if (!isoStr) return '-';
                try {
                    const d = new Date(isoStr);
                    return d.toLocaleDateString('id-ID', {
                        day: '2-digit', month: 'short', year: 'numeric',
                        hour: '2-digit', minute: '2-digit'
                    });
                } catch {
                    return isoStr;
                }
            }
        }));
        window._manajemenLinenRegistered = true;
    }
}
