$(function() {
    function WebDavBackupViewModel(parameters){
        var self = this;

        self.settingsViewModel = parameters[0];

        self.testing_connection = ko.observable(false);
        self.test_succeeded = ko.observable(false);
        self.test_failed = ko.observable(false);

        self.testWebDavConnection = function(data) {
            console.log("WebDavBackup test_connection");
            self.test_succeeded(false);
            self.test_failed(false);
            self.testing_connection(true);
            OctoPrint.simpleApiCommand("webdavbackup", "test_connection")
                .done(function(response) {
                    console.log(response);
                    self.testing_connection(false);
                    self.test_succeeded(response.success);
                    self.test_failed(!response.success);
                });
        };
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: WebDavBackupViewModel,
        dependencies: ["settingsViewModel"],
        elements: ["#settings_plugin_webdavbackup"],
    });
})