$(function() {
    function WebDavBackupViewModel(parameters){
        var self = this;

        self.settingsViewModel = parameters[0];

        self.testing_connection = ko.observable(false);
        self.test_succeeded = ko.observable(false);
        self.test_failed = ko.observable(false);
        self.response_message = ko.observable();

        self.testWebDavConnection = function(data) {
            console.log("WebDavBackup test_connection");
            self.test_succeeded(false);
            self.test_failed(false);
            self.testing_connection(true);
            self.response_message('');
            OctoPrint.simpleApiCommand("webdavbackup", "test_connection")
                .done(function(response) {
                    console.log(response);
                    self.testing_connection(false);
                    self.test_succeeded(response.success);
                    self.test_failed(!response.success);
                    self.response_message(response.message);
                });
        };

        self.onBeforeBinding = function(data) {
            self.test_succeeded(false);
            self.test_failed(false);
            self.testing_connection(false);
        }
    }

    OCTOPRINT_VIEWMODELS.push({
        construct: WebDavBackupViewModel,
        dependencies: ["settingsViewModel"],
        elements: ["#settings_plugin_webdavbackup"],
    });
})