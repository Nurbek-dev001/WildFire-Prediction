Attributes {
    latitude {
        String units "degrees_north";
        String long_name "latitude";
        String axis "Y";
        String standard_name "latitude";
        String bounds "lat_bnds";
    }
    longitude {
        String units "degrees_east";
        String long_name "longitude";
        String axis "X";
        String standard_name "longitude";
        String bounds "lon_bnds";
    }
    time {
        String units "days since 1981-01-01 00:00:00";
        String long_name "time";
        String axis "T";
        String standard_name "time";
        String calendar "gregorian";
    }
    crs {
        String grid_mapping_name "latitude_longitude";
        String epsg_code "EPSG:4326";
        Float64 longitude_of_prime_meridian 0.0;
        Float64 semi_major_axis 6378137.0;
        Float64 inverse_flattening 298.257223563;
    }
    lat_bnds {
    }
    lon_bnds {
    }
    NDVI {
        Float64 scale_factor 1.0E-4;
        Float64 add_offset 0.0;
        String long_name "NOAA Climate Data Record of Normalized Difference Vegetation Index";
        String units "1";
        Int16 valid_range -1000, 10000;
        Int16 _FillValue -9999;
        String grid_mapping "crs";
        String standard_name "normalized_difference_vegetation_index";
        UInt32 _ChunkSizes 1, 1200, 2400;
    }
    TIMEOFDAY {
        Float64 scale_factor 0.01;
        Float64 add_offset 0.0;
        String long_name "Time since Start of Data Day";
        String units "hours since 2020-12-27 00:00:00";
        Int16 valid_range 0, 2399;
        Int16 _FillValue -9999;
        String grid_mapping "crs";
        UInt32 _ChunkSizes 1, 1200, 2400;
    }
    QA {
        UInt32 flag_values 32768, 0, 1024, 0, 512, 0, 256, 0, 0, 64, 128, 192, 0, 8, 16, 24, 40, 4, 0, 0, 1, 2, 3;
        UInt32 flag_masks 32768, 32768, 1024, 1024, 512, 512, 256, 256, 192, 192, 192, 192, 56, 56, 56, 56, 56, 4, 4, 3, 3, 3, 3;
        String flag_meanings "\x03\x03snow-ice_flag_snow-ice snow-ice_flag_no_snow-ice cloud_flag_cloud cloud_flag_no_cloud thin_cirrus_emissive_yes thin_cirrus_emissive_no thin_cirrus_reflective_yes thin_cirrus_reflective_no aerosol_quantity:_level_of_uncertainty_in_aerosol_correction_climatology aerosol_quantity:_level_of_uncertainty_in_aerosol_correction_low aerosol_quantity:_level_of_uncertainty_in_aerosol_correction_average aerosol_quantity:_level_of_uncertainty_in_aerosol_correction_high land-water_flag_land_and_desert land-water_flag_land_no_desert land-water_flag_inland_water land-water_flag_sea_water land-water_flag_coastal cloud_shadow_yes cloud_shadow_no cloud_state_confident_clear cloud_state_probably_clear cloud_state_probably_cloudy cloud_state_confident_cloudy ";
        String long_name "Quality Assurance";
        String grid_mapping "crs";
    }
    NC_GLOBAL {
        String title "Normalized Difference Vegetation Index parameters derived from S-NPP CMG data for day 2020/362";
        String institution "NASA/GSFC/SED/ESD/HBSL/TIS/MODIS-LAND > MODIS Land Science Team, Terrestrial Information Systems,  Hydrospheric and Biospheric Science Laboratory, Earth Sciences Division, Science and Exploration Directorate, Goddard Space Flight Center, NASA";
        String Conventions "CF-1.6, ACDD-1.3";
        String standard_name_vocabulary "CF Standard Name Table (v25, 05 July 2013)";
        String naming_authority "gov.noaa.ncei";
        String license "See the Use Agreement for this CDR available from the NOAA CDR webpage";
        String cdm_data_type "Grid";
        String time_coverage_start "2020-12-27T00:00:00Z";
        String time_coverage_end "2020-12-27T23:59:59Z";
        String product_version "v2r0";
        String platform "Suomi-NPP > Suomi National Polar-orbiting Partnership";
        String sensor "VIIRS > Visible Infrared Imaging Radiometer Suite";
        String keywords_vocabulary "NASA Global Change Master Directory (GCMD) Science Keywords";
        String platform_vocabulary "Global Change Master Directory (GCMD) Platform Keywords";
        String instrument_vocabulary "Global Change Master Directory (GCMD) Instrument Keywords";
        String keywords "EARTH SCIENCE > BIOSPHERE > VEGETATION > VEGETATION INDEX";
        String source "BRDFCOR_VNP09CMG.A2020362.002.2023069164414.hdf";
        String date_created "2024-01-27T03:15:56Z";
        String spatial_resolution "0.050000 degrees per pixel";
        Float32 geospatial_lat_min -90.0;
        Float32 geospatial_lat_max 90.0;
        Float32 geospatial_lon_min -180.0;
        Float32 geospatial_lon_max 180.0;
        String metadata_link "https://doi.org/10.7289/V5ZG6QH9";
        String program "NOAA Climate Data Record Program for satellites";
        String cdr_variable "NDVI";
        String Process "MODAPS";
        String PostProcessingVersion "2.10";
        String VersionId "002";
        String Satellite "S-NPP";
        String Instrument "VIIRS";
        String InputDataType "VIIRS CMG";
        String summary "S-NPP CMG data for 2020, days 362 to 362, processed by the Long-Term Land Data Record (LTDR) project (v2) into normalized difference vegetation index (NDVI) and quality-control flags. ";
        String ProductionTime "2024-01-27T03:15:56.000000Z";
        String ShortName "NPP13C1";
        String identifier_product_doi "10.5067/AVHRR/NPP13C1.002";
        String identifier_product_doi_authority "https://www.doi.org";
        String LongName "S-NPP Atmospherically Corrected Normalized Difference Vegitation Index Daily L3 Global 0.05 Deg CMG NetCDF";
        String LocalGranuleID "VIIRS-Land_v002_NPP13C1_S-NPP_20201227_c20240127031556.nc";
        String id "VIIRS-Land_v002_NPP13C1_S-NPP_20201227_c20240127031556.nc";
        String RangeBeginningDate "2020-12-27";
        String RangeBeginningTime "00:00:00.0000";
        String RangeEndingDate "2020-12-27";
        String RangeEndingTime "23:59:59.9999";
    }
}
